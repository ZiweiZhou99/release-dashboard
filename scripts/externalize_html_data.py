#!/usr/bin/env python3
"""Remove embedded dashboard data from HTML and inject JSON fetch loader."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

LOADER = r"""
// ─── Data (loaded from /upload-api/data/*.json) ───
let R = [], TK = [], FB_RAW = [], SF_RAW = [], SF = [], FB = [];
const DATA_API = '/upload-api/data';

function rebuildSF() {
  SF = SF_RAW.map(r => ({
    time: r[0], module: r[1], desc: r[2], grade: r[3], city: r[4],
    textbook: r[5], submitter: r[6], reply: r[7], status: r[8],
  }));
}

function rebuildFeedbackDerived() {
  FB = FB_RAW.map(r => ({
    userId: r[0], desc: r[1], category: r[2], device: r[3], source: r[4], time: r[5],
  }));
}

async function fetchDataJson(name) {
  const res = await fetch(`${DATA_API}/${name}.json`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.json();
}

function normalizeTickets(data) {
  if (!data || !data.length) return [];
  if (typeof data[0] === 'object' && !Array.isArray(data[0])) return data;
  const header = data[0].map(h => String(h || '').trim());
  return data.slice(1).map(row => {
    const obj = {};
    header.forEach((key, i) => { obj[key] = row[i] != null ? String(row[i]) : ''; });
    if (obj.id && !obj.url && obj.id.match(/^\d+$/)) {
      obj.url = `https://work-order.zhenguanyu.com/next/#/znyj/ticket/detail/${obj.id}`;
    }
    return obj;
  });
}

function resetSelectOptions(id) {
  const el = document.getElementById(id);
  if (el) el.options.length = 1;
}

function resetVoicesFilters(types) {
  (types || ['tickets', 'feedback', 'store']).forEach(type => {
    if (type === 'tickets') ['tkClfFilter', 'tkDevFilter'].forEach(resetSelectOptions);
    if (type === 'feedback') ['fbProductFilter', 'fbTypeFilter'].forEach(resetSelectOptions);
    if (type === 'store') ['sfModuleFilter', 'sfCityFilter'].forEach(resetSelectOptions);
  });
}

function setDataLoadStatus(state, message) {
  const tr = document.getElementById('tR');
  const tf = document.getElementById('tF');
  if (!tr || !tf) return;
  if (state === 'loading') {
    tr.textContent = '…';
    tf.textContent = '…';
    tr.title = message || '正在加载数据';
    return;
  }
  if (state === 'error') {
    tr.textContent = '!';
    tf.textContent = '!';
    tr.title = message || '数据加载失败';
    return;
  }
  tr.textContent = String(R.length);
  tf.textContent = String(R.reduce((s, r) => s + r.features.length, 0));
  tr.title = '';
}

async function loadDashboardData(options) {
  options = options || {};
  const only = options.only;
  const need = only || ['releases', 'tickets', 'feedback', 'store'];
  if (!only) setDataLoadStatus('loading');

  try {
    const loaders = {
      releases: async () => { R = await fetchDataJson('releases') || []; },
      tickets: async () => { TK = normalizeTickets(await fetchDataJson('tickets')) || []; },
      feedback: async () => { FB_RAW = await fetchDataJson('feedback') || []; rebuildFeedbackDerived(); },
      store: async () => { SF_RAW = await fetchDataJson('store') || []; rebuildSF(); },
    };
    await Promise.all(need.map(key => loaders[key]()));

    if (!only) {
      onDashboardDataReady();
    } else {
      if (only.includes('releases')) init();
      if (only.some(k => ['tickets', 'feedback', 'store'].includes(k))) {
        resetVoicesFilters(only);
        if (only.includes('tickets') && currentVoicesTab === 'tickets') renderTickets();
        if (only.includes('feedback') && currentVoicesTab === 'feedback') initFeedback();
        if (only.includes('store') && currentVoicesTab === 'store') renderStore();
      }
    }
    setDataLoadStatus('ok');
    return true;
  } catch (err) {
    console.error('loadDashboardData failed', err);
    setDataLoadStatus('error', err.message || String(err));
    return false;
  }
}

function onDashboardDataReady() {
  init();
}

async function reloadVoicesData(type) {
  const map = { tickets: ['tickets'], feedback: ['feedback'], store: ['store'] };
  const ok = await loadDashboardData({ only: map[type] || ['tickets', 'feedback', 'store'] });
  if (ok) switchVoicesTab(currentVoicesTab);
  return ok;
}
""".strip()


def remove_const_line(lines: list[str], index: int, names: list[str]) -> None:
    line = lines[index]
    for name in names:
        if re.search(rf"const\s+{re.escape(name)}\s*=", line):
            lines[index] = ""
            return
    raise ValueError(f"line {index + 1} does not contain {names}")


def transform_html(html: str) -> str:
    lines = html.splitlines()

    # Line numbers are 1-based in editor; convert to 0-based indexes.
    idx = {name: i for i, line in enumerate(lines) for name in [
        "FB_RAW", "SF_RAW", "R", "TK"
    ] if re.search(rf"const\s+{name}\s*=", line)}

    if len(idx) < 4:
        missing = {"FB_RAW", "SF_RAW", "R", "TK"} - set(idx)
        raise ValueError(f"embedded constants already removed or missing: {missing}")

    # Replace FB_RAW line with loader + open script tag context preserved.
    fb_line = lines[idx["FB_RAW"]]
    if fb_line.startswith("<script>"):
        lines[idx["FB_RAW"]] = "<script>\n" + LOADER
    else:
        lines[idx["FB_RAW"]] = LOADER

    lines[idx["SF_RAW"]] = "// SF_RAW loaded via loadDashboardData()"
    lines[idx["R"]] = "// R loaded via loadDashboardData()"
    lines[idx["TK"]] = "// TK loaded via loadDashboardData()"

    for i, line in enumerate(lines):
        if line.startswith("const SF = SF_RAW.map"):
            lines[i] = "// SF rebuilt via rebuildSF()"
            break

    # FB derived data
    html = "\n".join(lines)
    html = html.replace(
        "const FB = (typeof FB_RAW !== 'undefined') ? FB_RAW.map(r=>({\n"
        "  userId:r[0], desc:r[1], category:r[2], device:r[3], source:r[4], time:r[5]\n"
        "})) : [];",
        "function rebuildFeedbackDerivedLegacy() { rebuildFeedbackDerived(); }",
    )

    html = re.sub(r"\ninit\(\);\s*\n", "\nloadDashboardData();\n\n", html, count=1)

    html = html.replace(
        "setTimeout(()=>{setUlStatus('✅ 成功！刷新页面后生效。','ok');},1500);",
        "setTimeout(async()=>{const ok=await reloadVoicesData(dataType);setUlStatus(ok?'✅ 数据已热更新':'⚠️ 上传成功但加载失败，请刷新页面','ok');},300);",
    )

    html = html.replace(
        "if(d.status==='done'){setTimeout(()=>{document.getElementById('updStatus').textContent='✅ 更新完成，正在刷新...';setTimeout(()=>location.reload(),1000);},500);}",
        "if(d.status==='done'){setTimeout(async()=>{document.getElementById('updStatus').textContent='✅ 更新完成，正在加载发版数据...';await loadDashboardData({only:['releases']});document.getElementById('updStatus').textContent='✅ 发版数据已更新';},500);}",
    )

    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="release-dashboard.html")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    path = Path(args.html)
    out = Path(args.out) if args.out else path
    original_size = path.stat().st_size
    html = transform_html(path.read_text(encoding="utf-8"))
    out.write_text(html, encoding="utf-8")
    new_size = out.stat().st_size
    print(f"✓ {out} {original_size // 1024} KB → {new_size // 1024} KB (-{(original_size - new_size) // 1024} KB)")


if __name__ == "__main__":
    main()
