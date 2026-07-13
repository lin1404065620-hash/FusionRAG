import os
import re
import sys
import time
import base64
from pathlib import Path
from typing import List, Tuple
from collections import deque

from minio.deleteobjects import DeleteObject

from app.clients.minio_utils import get_minio_client
from app.import_process.agent.state import ImportGraphState
from app.utils.task_utils import add_running_task, add_done_task
from app.lm.lm_utils import get_llm_client
from app.conf.minio_config import minio_config
from app.conf.lm_config import lm_config
from app.core.logger import logger
from app.utils.rate_limit_utils import apply_api_rate_limit
from app.core.load_prompt import load_prompt

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def is_supported_image(filename: str) -> bool:
    """判断文件是否为支持的图片格式（后缀不区分大小写）。"""
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS


def step_1_get_content(state: ImportGraphState) -> Tuple[str, Path, Path]:
    """从 state 中提取 md_content、md 路径对象和 images 目录对象。"""
    md_file_path = state["md_path"]
    if not md_file_path:
        raise ValueError("md_path不能为空！")

    md_path_obj = Path(md_file_path)
    if not md_path_obj.exists():
        raise FileNotFoundError(f"md_path:{md_file_path} 文件不存在！")

    if not state['md_content']:
        with md_path_obj.open("r", encoding="utf-8") as f:
            state['md_content'] = f.read()

    images_dir_obj = md_path_obj.parent / "images"
    return state['md_content'], md_path_obj, images_dir_obj


def find_image_in_md_content(md_content, image_file, context_length: int = 100):
    """
    在 md_content 中查找图片引用，并截取该图片前后各 context_length 字的上下文。
    返回 (上文, 下文) 元组，未找到则返回 None。
    """
    pattern = re.compile(r"!\[.*?\]\(.*?" + image_file + r".*?\)")
    items = list(pattern.finditer(md_content))
    if not items:
        return None
    if item := items[0]:
        start, end = item.span()
        pre_text = md_content[max(start - context_length, 0):start]
        post_text = md_content[end:min(end + context_length, len(md_content))]
        content = (pre_text, post_text)
    if content:
        logger.info(f"图片：{image_file}, 截取第一个上下文：{content}")
        return content


def step_2_scan_images(md_content: str, images_dir_obj: Path) -> List[Tuple[str, str, Tuple[str, str]]]:
    """
    扫描 images 目录中的图片，识别在 md 中使用的图片并截取上下文。
    返回 [(图片名, 图片本地路径, (上文, 下文)), ...]
    """
    targets = []
    for image_file in os.listdir(images_dir_obj):
        if not is_supported_image(image_file):
            logger.warning(f"当前文件：{image_file},不是图片格式，无需处理！")
            continue
        content_data = find_image_in_md_content(md_content, image_file)
        if not content_data:
            logger.warning(f"图片：{image_file}没有在md内容使用！上下文为空！")
            continue
        targets.append((image_file, str(images_dir_obj / image_file), content_data))
    return targets


def step_3_generate_img_summaries(targets, stem):
    """
    利用视觉模型为每张图片生成描述。
    targets: [(图片名, 图片本地路径, (上文, 下文)), ...]
    返回 {图片名: 描述, ...}
    """
    summaries = {}
    request_times = deque()
    for image_file, image_path, context in targets:
        apply_api_rate_limit(request_times, max_requests=9)
        for attempt in range(3):
            try:
                vm_model = get_llm_client(model=lm_config.lv_model)
                prompt = load_prompt("image_summary", root_folder=stem, image_content=context)
                with open(image_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode("utf-8")
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                },
                            },
                            {"type": "text", "text": f"{prompt}"},
                        ],
                    },
                ]
                response = vm_model.invoke(messages)
                summary = response.content.strip().replace("\n", "")
                summaries[image_file] = summary
                logger.info(f"图片：{image_file}，总结结果：{summary}")
                break
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"图片 {image_file} API调用失败(第{attempt + 1}次): {e}，{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    logger.error(f"图片 {image_file} 已达最大重试次数，跳过: {e}")
                    summaries[image_file] = ""
    logger.info(f"总结图片，获取结果：{summaries}")
    return summaries


def step_4_upload_images_and_replace_md(summaries, targets, md_content, stem):
    """
    上传图片到 MinIO，并用 AI 描述 + MinIO 公网 URL 替换 md 中的原始图片引用。
    """
    minio_client = get_minio_client()
    if minio_client is None:
        logger.warning("MinIO 不可用，跳过图片上传，保留本地路径")
        return md_content

    # 删除 MinIO 中对应 stem 目录的旧图片（幂等覆盖）
    object_list = minio_client.list_objects(
        minio_config.bucket_name,
        prefix=f"{minio_config.minio_img_dir[1:]}/{stem}",
        recursive=True
    )
    delete_object_list = [DeleteObject(obj.object_name) for obj in object_list]
    errors = minio_client.remove_objects(minio_config.bucket_name, delete_object_list)
    for errors in errors:
        logger.error(f"删除对象失败：{errors}")
    logger.info(f"已经完成{stem}下的对象清空，本次删除了：{len(delete_object_list)}个对象！！！")

    images_url = {}
    for image_file, image_path, _ in targets:
        try:
            minio_client.fput_object(
                bucket_name=minio_config.bucket_name,
                object_name=f"{minio_config.minio_img_dir}/{stem}/{image_file}",
                file_path=image_path,
                content_type="image/jpeg"
            )
            images_url[image_file] = (
                f"http://{minio_config.endpoint}/{minio_config.bucket_name}"
                f"{minio_config.minio_img_dir}/{stem}/{image_file}"
            )
            logger.info(f"完成图片{image_file}上传，访问地址为：{images_url[image_file]}")
        except Exception as e:
            logger.error(f"上传图片失败：{image_file}，失败原因：{e}")

    # 合并 summaries 和 images_url
    image_infos = {}
    for image_file, summary in summaries.items():
        if url := images_url.get(image_file):
            image_infos[image_file] = (summary, url)
    logger.info(f"图片处理的汇总结果:{image_infos}")

    if image_infos:
        for image_file, (summary, url) in image_infos.items():
            rep = re.compile(r"!\[.*?\]\(.*?" + image_file + r".*?\)")
            md_content = rep.sub(lambda _: f"![{summary}]({url})", md_content)
        logger.info(f"已经完成md内容的替换，新的内容为:{md_content}")
    return md_content


def step_5_replace_md_and_save(new_md_content, md_path_obj):
    """
    将新 md 内容写入 _new.md 文件，返回新路径。
    """
    new_md_path_str = os.path.splitext(md_path_obj)[0] + "_new.md"
    with open(new_md_path_str, "w", encoding="utf-8") as f:
        f.write(new_md_content)
    logger.info(f"已经完成了新内容的写入，新的地址为:{new_md_path_str}")
    return new_md_path_str


def node_md_img(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 图片处理 (node_md_img)
    处理 Markdown 中的图片资源：扫描图片 -> 视觉模型描述 -> 上传 MinIO -> 替换引用。
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)

    md_content, md_path_obj, images_dir_obj = step_1_get_content(state)
    if not images_dir_obj.exists():
        logger.info(f">>> [{function_name}]没有图片，直接返回 state ！")
        return state

    targets = step_2_scan_images(md_content, images_dir_obj)
    summaries = step_3_generate_img_summaries(targets, md_path_obj.stem)
    new_md_content = step_4_upload_images_and_replace_md(summaries, targets, md_content, md_path_obj.stem)
    new_md_file_path = step_5_replace_md_and_save(new_md_content, md_path_obj)

    state["md_path"] = new_md_file_path
    state["md_content"] = new_md_content

    logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
    add_done_task(state['task_id'], function_name)
    return state
