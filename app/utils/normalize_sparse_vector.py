import numpy as np


def normalize_sparse_vector(sparse_vec):
    """
    对稀疏向量做 L2 归一化（仅处理非零维度，不影响零维度）
    :param sparse_vec: 原始稀疏向量（dict 格式：{维度: 数值}）
    :return: 归一化后的稀疏向量
    """
    if not sparse_vec:
        return sparse_vec

    values = np.array(list(sparse_vec.values()), dtype=np.float64)
    l2_norm = np.linalg.norm(values)
    if l2_norm < 1e-9:
        return sparse_vec

    normalized_values = values / l2_norm
    return dict(zip(sparse_vec.keys(), normalized_values))
