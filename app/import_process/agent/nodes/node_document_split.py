import re
import json
import os
import sys

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.utils.task_utils import add_running_task, add_done_task
from app.import_process.agent.state import ImportGraphState
from app.core.logger import logger

DEFAULT_MAX_CONTENT_LENGTH = 512
MIN_CONTENT_LENGTH = 50


def step_1_get_content(state):
    """读取并预处理 md_content，统一换行符为 \\n。"""
    md_content = state['md_content']
    if not md_content:
        logger.error("[step_1_get_content]没有有效的md内容，直接抛出异常！！！！")
        raise Exception("请检查输入文件路径是否正确！！")

    md_content = md_content.replace('\r\n', '\n').replace('\r', '\n')
    file_title = state.get("file_title", "default_file")
    return md_content, file_title


def step_2_split_by_title(md_content, file_title):
    """
    按 Markdown 标题进行语义粗切分，返回 sections 列表。
    代码块中的 # 不会被误判为标题。
    """
    title_pattern = r'^\s*#{1,6}\s+.+'
    lines = md_content.split('\n')

    current_title = ""
    current_lines = []
    title_count = 0
    is_code_block = False
    sections = []

    for line in lines:
        strip_line = line.strip()

        if strip_line.startswith('```') or strip_line.startswith('~~~'):
            is_code_block = not is_code_block
            current_lines.append(line)
            continue

        is_title = (not is_code_block) and re.match(title_pattern, strip_line)

        if is_title:
            if current_title:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_lines),
                    "file_title": file_title
                })
            current_title = strip_line
            current_lines = [current_title]
            title_count += 1
        else:
            current_lines.append(line)

    # 保存最后一个标题块
    if current_title:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines),
            "file_title": file_title
        })

    logger.info(f"已经完成chunks的语义粗切！识别chunk数量：{title_count},切片内容:{sections}")
    return sections, title_count, len(lines)


def split_long_section(section, max_length):
    """对超长 section 使用 RecursiveCharacterTextSplitter 进行二次切割。"""
    content = section.get("content")
    if len(content) <= max_length:
        logger.info(f"[split_long_section]当前chunk长度小于等于{max_length}，不做二次切割！")
        return [section]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_length,
        chunk_overlap=2,
        separators=['\n\n', '\n', '。', '！', "；", " "]
    )

    sub_sections = []
    for index, chunk in enumerate(splitter.split_text(content), start=1):
        text = chunk.strip()
        sub_sections.append({
            "title": f"{section.get('title')}_{index}",
            "content": text,
            "file_title": section.get("file_title"),
            "parent_title": section.get("title"),
            "part": index
        })

    return sub_sections


def merge_short_sections(final_sections, min_length):
    """
    合并过短的 chunk：只有同属一个 parent_title 且内容过短才会合并。
    """
    merged_sections = []
    pre_section = None

    for section in final_sections:
        if pre_section is None:
            pre_section = section
            continue

        is_pre_short = len(pre_section.get("content")) < min_length
        is_same_parent_title = (
            pre_section.get("parent_title")
            and pre_section.get("parent_title") == section.get("parent_title")
        )

        if is_pre_short and is_same_parent_title:
            pre_section["content"] += "\n\n" + section.get("content")
            pre_section['part'] = section.get("part")
        else:
            merged_sections.append(pre_section)
            pre_section = section

    if pre_section is not None:
        merged_sections.append(pre_section)

    return merged_sections


def step_3_refine_chunks(sections, max_length, min_length):
    """
    精细切割：长的切短，短的合并，并补齐 part 和 parent_title 字段。
    """
    final_sections = []
    for section in sections:
        sub_section = split_long_section(section, max_length)
        final_sections.extend(sub_section)

    final_sections = merge_short_sections(final_sections, min_length)

    for section in final_sections:
        section['part'] = section.get('part') or 1
        section['parent_title'] = section.get('parent_title') or section.get('title')

    return final_sections


def step_4_backup_chunks(state, sections):
    """将切割完成的 chunks 备份到 local_dir/chunks.json。"""
    local_dir = state.get("local_dir")
    backup_file_path = os.path.join(local_dir, "chunks.json")
    with open(backup_file_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, ensure_ascii=False, indent=4)
    logger.info(f"已经将内容,进行备份到:{backup_file_path}")


def node_document_split(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 文档切分 (node_document_split)
    将长文档切分成小的 Chunks (切片) 以便检索。
    流程：标题粗切 -> 超长二次切 -> 过短合并 -> 备份。
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)
    try:
        md_content, file_title = step_1_get_content(state)
        sections, title_count, lines_count = step_2_split_by_title(md_content, file_title)

        if title_count == 0:
            sections = [{"title": "没有主题", "content": md_content, "file_title": file_title}]

        sections = step_3_refine_chunks(sections, DEFAULT_MAX_CONTENT_LENGTH, MIN_CONTENT_LENGTH)
        state['chunks'] = sections
        step_4_backup_chunks(state, sections)
    except Exception as e:
        logger.error(f">>> [{function_name}]使用minerU解析发生了异常，异常信息：{e}")
        raise
    finally:
        logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
        add_done_task(state['task_id'], function_name)

    return state
