"""Milvus 数据库网页可视化工具 — 启动后浏览器打开 http://127.0.0.1:5050"""

import os
from flask import Flask, jsonify, request
from pymilvus import MilvusClient

app = Flask(__name__)
MILVUS_DB = os.environ.get("MILVUS_DB_PATH", "./milvus_data/milvus.db")


def get_client():
    os.makedirs(os.path.dirname(MILVUS_DB), exist_ok=True)
    return MilvusClient(MILVUS_DB)


@app.route("/")
def index():
    return """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Milvus 数据库查看器</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: Consolas, monospace; background: #1a1a2e; color: #eee; padding: 20px; }
h1 { color: #00d4aa; margin-bottom: 20px; }
h2 { color: #00a8cc; margin: 15px 0 10px; }
.collections { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
.col-btn { background: #16213e; color: #00d4aa; border: 1px solid #00d4aa; padding: 8px 16px; cursor: pointer; border-radius: 4px; }
.col-btn:hover, .col-btn.active { background: #00d4aa; color: #1a1a2e; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
th { background: #16213e; color: #00a8cc; padding: 10px 8px; text-align: left; position: sticky; top: 0; }
td { padding: 8px; border-bottom: 1px solid #333; max-width: 500px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
tr:hover { background: #1f3050; }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 15px; flex-wrap: wrap; }
.toolbar input { background: #16213e; border: 1px solid #444; color: #eee; padding: 6px 10px; border-radius: 4px; }
.toolbar input[type="number"] { width: 80px; }
.toolbar button { background: #0f3460; color: #eee; border: none; padding: 6px 14px; cursor: pointer; border-radius: 4px; }
.toolbar button:hover { background: #1a5080; }
.info { color: #888; font-size: 12px; margin-bottom: 10px; }
.field-list { color: #888; font-size: 12px; margin-top: 5px; }
.loading { color: #f90; }
.error { color: #f44; }
.data-wrap { max-height: 60vh; overflow-y: auto; border: 1px solid #333; border-radius: 4px; }
</style>
</head>
<body>
<h1>Milvus 数据库查看器</h1>
<div class="collections" id="collections"></div>
<div class="info" id="info"></div>
<div class="toolbar">
    <span>筛选:</span>
    <input id="filter" placeholder="pk >= 0" value="pk >= 0">
    <span>条数:</span>
    <input id="limit" type="number" value="100" min="1" max="1000">
    <button onclick="loadData()">查询</button>
</div>
<div class="field-list" id="fields"></div>
<div class="data-wrap"><table id="data"><thead><tr></tr></thead><tbody></tbody></table></div>

<script>
let activeCol = '';
async function init() {
    try {
        const res = await fetch('/api/collections');
        const data = await res.json();
        const div = document.getElementById('collections');
        if (data.collections.length === 0) {
            div.innerHTML = '<span style="color:#888">暂无集合</span>';
            return;
        }
        data.collections.forEach(c => {
            const btn = document.createElement('button');
            btn.className = 'col-btn';
            btn.textContent = c;
            btn.onclick = () => { activeCol = c; document.querySelectorAll('.col-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active'); loadFields(); loadData(); };
            div.appendChild(btn);
        });
        activeCol = data.collections[0];
        div.querySelector('.col-btn').classList.add('active');
        loadFields();
        loadData();
    } catch(e) { document.getElementById('info').innerHTML = '<span class="error">连接失败</span>'; }
}
async function loadFields() {
    if (!activeCol) return;
    const res = await fetch('/api/schema/' + activeCol);
    const data = await res.json();
    document.getElementById('fields').textContent = '字段: ' + (data.fields || []).join(', ');
}
async function loadData() {
    if (!activeCol) return;
    const info = document.getElementById('info');
    info.innerHTML = '<span class="loading">加载中...</span>';
    try {
        const filter = document.getElementById('filter').value;
        const limit = document.getElementById('limit').value;
        const res = await fetch(`/api/query/${activeCol}?filter=${encodeURIComponent(filter)}&limit=${limit}`);
        const data = await res.json();
        if (data.error) { info.innerHTML = `<span class="error">${data.error}</span>`; return; }
        info.textContent = `${activeCol} — 共 ${data.count} 条`;
        const thead = document.querySelector('#data thead tr');
        const tbody = document.querySelector('#data tbody');
        thead.innerHTML = '';
        tbody.innerHTML = '';
        data.fields.forEach(f => { const th = document.createElement('th'); th.textContent = f; thead.appendChild(th); });
        data.rows.forEach(row => {
            const tr = document.createElement('tr');
            data.fields.forEach(f => { const td = document.createElement('td'); td.textContent = JSON.stringify(row[f]) || ''; td.title = td.textContent; tr.appendChild(td); });
            tbody.appendChild(tr);
        });
    } catch(e) { info.innerHTML = `<span class="error">查询失败: ${e.message}</span>`; }
}
init();
</script>
</body>
</html>"""


@app.route("/api/collections")
def api_collections():
    try:
        c = get_client()
        cols = c.list_collections()
        c.close()
        return jsonify({"collections": cols})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/schema/<collection>")
def api_schema(collection):
    try:
        c = get_client()
        desc = c.describe_collection(collection)
        fields = [f["name"] for f in desc.get("fields", [])]
        c.close()
        return jsonify({"fields": fields})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/query/<collection>")
def api_query(collection):
    try:
        c = get_client()
        c.load_collection(collection)
        filter_expr = request.args.get("filter", "pk >= 0")
        limit = int(request.args.get("limit", 100))
        res = c.query(collection_name=collection, filter=filter_expr, limit=limit, output_fields=["*"])
        fields = list(res[0].keys()) if res else []
        c.close()
        return jsonify({"fields": fields, "rows": res, "count": len(res)})
    except Exception as e:
        return jsonify({"error": str(e)}, 500)


if __name__ == "__main__":
    print(f"访问 http://127.0.0.1:5050 查看数据库")
    app.run(host="0.0.0.0", port=5050, debug=False)
