import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

from app.core.logger import logger
from app.import_process.agent.state import ImportGraphState
from app.utils.task_utils import add_running_task, add_done_task
from app.utils.path_util import PROJECT_ROOT
from app.conf.mineru_config import mineru_config


def step_1_validate_paths(state):
    """
    路径校验：pdf_path 不存在则抛异常，local_dir 不存在则给默认值。
    """
    logger.debug(">>> [step_1_validate_paths]在md转pdf下，开始进行文件格式校验！！")
    pdf_path = state['pdf_path']
    local_dir = state['local_dir']

    if not pdf_path:
        logger.error("step_1_validate_paths检查发现没有输入文件，无法继续解析！！")
        raise ValueError("step_1_validate_paths检查发现没有输入文件，无法继续解析！！")
    if not local_dir:
        local_dir = PROJECT_ROOT / "output"
        logger.info(f"step_1_validate_paths检查发现local_dir没有赋值，给与默认值：{local_dir}！")

    pdf_path_obj = Path(pdf_path)
    local_dir_obj = Path(local_dir)

    if not pdf_path_obj.exists():
        logger.error("[step_1_validate_paths检查发现pdf_path不存在，请检查输入文件路径是否正确！！")
        raise FileNotFoundError("[step_1_validate_paths]检查发现pdf_path不存在，请检查输入文件路径是否正确！！")
    if not local_dir_obj.exists():
        logger.error("[step_1_validate_paths检查发现local_dir不存在，主动创建对应的文件夹！！！")
        local_dir_obj.mkdir(parents=True, exist_ok=True)

    return pdf_path_obj, local_dir_obj


def step_2_upload_and_poll(pdf_path_obj) -> str:
    """
    将 PDF 文件上传到 MinerU 进行解析，轮询直至解析完成，返回结果 zip 的下载地址。
    最多等待 600 秒，每 3 秒轮询一次。
    """
    token = mineru_config.api_key
    url = f"{mineru_config.base_url}/file-urls/batch"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [
            {"name": f"{pdf_path_obj.name}"}
        ],
        "model_version": "vlm"
    }
    response = requests.post(url, headers=header, json=data)
    if response.status_code != 200 or response.json()['code'] != 0:
        logger.error(
            f"[step_2_upload_and_poll]请求minerU解析接口失败！"
            f"status_code={response.status_code}, "
            f"response_body={response.text[:500]}, "
            f"url={url}"
        )
        raise RuntimeError(
            f"[step_2_upload_and_poll]请求minerU解析接口失败！"
            f"status={response.status_code}, body={response.text[:300]}"
        )
    uploaded_url = response.json()['data']['file_urls'][0]
    batch_id = response.json()['data']['batch_id']

    # PUT 上传 PDF 到 MinerU, 使用 Session 并禁用代理
    http_session = requests.Session()
    http_session.trust_env = False
    try:
        with open(pdf_path_obj, 'rb') as f:
            file_data = f.read()
        upload_response = http_session.put(uploaded_url, data=file_data)
        if upload_response.status_code != 200:
            logger.error("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
            raise RuntimeError("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
    except Exception as e:
        logger.error("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
    finally:
        http_session.close()

    # 轮询获取解析结果
    url = f"{mineru_config.base_url}/extract-results/batch/{batch_id}"
    timeout_seconds = 600
    poll_interval = 3
    start_time = time.time()

    while True:
        if time.time() - start_time > timeout_seconds:
            logger.error("[step_2_upload_and_poll]请求minerU解析接口超时，请检查输入文件路径是否正确！！")
            raise TimeoutError("[step_2_upload_and_poll]请求minerU解析接口超时，请检查输入文件路径是否正确！！")

        res = requests.get(url, headers=header)
        if res.status_code != 200:
            if 500 <= res.status_code < 600:
                time.sleep(poll_interval)
                continue
            raise RuntimeError(f"[step_2_upload_and_poll]请求minerU解析接口失败，返回的状态码{res.status_code}！！")

        json_data = res.json()
        if json_data['code'] != 0:
            raise RuntimeError(f"[step_2_upload_and_poll]请求minerU解析接口失败，返回的错误:{json_data['code']}信息{json_data['msg']}！！")

        extract_result = json_data['data']['extract_result'][0]
        if extract_result['state'] == 'done':
            full_zip_url = extract_result['full_zip_url']
            logger.info(f"已经完成pdf的解析，耗时：{time.time() - start_time}s,解析结果：{full_zip_url}")
            return full_zip_url
        else:
            time.sleep(poll_interval)


def step_3_download_and_extract(zip_url, local_dir_obj, stem) -> str:
    """
    下载 MinerU 返回的 zip 文件，解压后返回最终 md 文件的绝对路径。
    优先选择 stem.md，其次 full.md，最后取第一个 md 文件。
    """
    response = requests.get(zip_url)
    if response.status_code != 200:
        logger.error("[step_3_download_and_extract]下载文件失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_3_download_and_extract]下载文件失败，请检查输入文件路径是否正确！！")

    zip_save_path = local_dir_obj / f"{stem}_result.zip"
    with open(zip_save_path, 'wb') as f:
        f.write(response.content)
    logger.info(f"[step_3_download_and_extract]下载文件成功，保存位置：{zip_save_path}")

    extract_target_dir = local_dir_obj / stem
    if extract_target_dir.exists():
        shutil.rmtree(extract_target_dir)
    extract_target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_save_path, 'r') as zip_file_object:
        zip_file_object.extractall(extract_target_dir)

    md_file_list = list(extract_target_dir.rglob("*.md"))
    if not md_file_list:
        logger.error("[step_3_download_and_extract]没有找到md文件，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_3_download_and_extract]没有找到md文件，请检查输入文件路径是否正确！！")

    target_md_file = None
    for md_file in md_file_list:
        if md_file.name == stem + ".md":
            target_md_file = md_file
            break

    if not target_md_file:
        for md_file in md_file_list:
            if md_file.name.lower() == "full.md":
                target_md_file = md_file
                break

    if not target_md_file:
        target_md_file = md_file_list[0]

    # 统一重命名为 stem.md
    if target_md_file.stem != stem:
        target_md_file = target_md_file.rename(target_md_file.with_name(f"{stem}.md"))

    final_md_str_path = str(target_md_file.resolve())
    logger.info(f"[step_3_download_and_extract]完成md解压，最终存储md路径为：{final_md_str_path}")
    return final_md_str_path


def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    节点: PDF转Markdown (node_pdf_to_md)
    将 PDF 非结构化数据通过 MinerU 转换为 Markdown 结构化数据。
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)
    try:
        pdf_path_obj, local_dir_obj = step_1_validate_paths(state)
        zip_url = step_2_upload_and_poll(pdf_path_obj)
        md_path = step_3_download_and_extract(zip_url, local_dir_obj, pdf_path_obj.stem)

        state['md_path'] = md_path
        state['local_dir'] = str(local_dir_obj)

        with open(md_path, 'r', encoding='utf-8') as f:
            state['md_content'] = f.read()
    except Exception as e:
        logger.error(f">>> [{function_name}]使用minerU解析发生了异常，异常信息：{e}")
        raise
    finally:
        logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
        add_done_task(state['task_id'], function_name)

    return state
