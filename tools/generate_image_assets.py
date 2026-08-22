# -*- coding: utf-8 -*-
"""为 300 题扩充批次生成图像鉴别任务所需的 SVG 示例资源。

每个 SVG 是一张含典型 AI 生成破绽的示意图片（几何图形组合），
供 image 型题目使用；破绽点由题干与评分量表描述，不写入图片本身。
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

SVGS = {
    # basic：城市夜景，路灯悬空（无灯柱）
    "img_basic_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<rect width="640" height="360" fill="#182848"/>
<rect x="0" y="330" width="640" height="30" fill="#0d1526"/>
<rect x="30" y="110" width="100" height="220" fill="#243a64"/>
<rect x="150" y="150" width="80" height="180" fill="#2b4370"/>
<rect x="250" y="80" width="90" height="250" fill="#1f3560"/>
<rect x="370" y="170" width="90" height="160" fill="#2a416c"/>
<rect x="490" y="120" width="80" height="210" fill="#233962"/>
<circle cx="560" cy="55" r="34" fill="#f6d876"/>
<g fill="#f9e9a8"><rect x="45" y="140" width="14" height="18"/><rect x="75" y="140" width="14" height="18"/><rect x="45" y="180" width="14" height="18"/><rect x="75" y="180" width="14" height="18"/><rect x="165" y="180" width="12" height="16"/><rect x="165" y="220" width="12" height="16"/><rect x="270" y="110" width="14" height="18"/><rect x="300" y="110" width="14" height="18"/><rect x="270" y="150" width="14" height="18"/><rect x="300" y="150" width="14" height="18"/><rect x="385" y="200" width="12" height="16"/><rect x="505" y="150" width="12" height="16"/><rect x="505" y="190" width="12" height="16"/></g>
<circle cx="330" cy="120" r="15" fill="#f8e9a1"/>
<rect x="326" y="135" width="9" height="12" fill="#f8e9a1"/>
<circle cx="330" cy="152" r="6" fill="#f8e9a1"/>
<text x="320" y="350" font-size="14" fill="#9fb4d8" font-family="sans-serif">城市夜景</text>
</svg>""",
    # basic：人像，右手六根手指
    "img_basic_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="560" viewBox="0 0 480 560">
<rect width="480" height="560" fill="#f2ede4"/>
<circle cx="240" cy="170" r="95" fill="#e8b88a"/>
<rect x="185" y="255" width="110" height="150" rx="28" fill="#e8b88a"/>
<rect x="150" y="390" width="180" height="120" rx="20" fill="#3a5a8c"/>
<rect x="255" y="395" width="18" height="70" fill="#e8b88a"/>
<g fill="#f4c999">
<rect x="282" y="392" width="14" height="66" rx="7"/><rect x="300" y="390" width="14" height="64" rx="7"/><rect x="318" y="388" width="14" height="62" rx="7"/><rect x="336" y="392" width="14" height="60" rx="7"/><rect x="354" y="394" width="14" height="58" rx="7"/></g>
<circle cx="205" cy="150" r="9" fill="#3b2a20"/><circle cx="275" cy="150" r="9" fill="#3b2a20"/>
<path d="M225 185 Q240 200 255 185" stroke="#3b2a20" stroke-width="5" fill="none"/>
<text x="180" y="540" font-size="14" fill="#7a6a5a" font-family="sans-serif">人物肖像</text>
</svg>""",
    # prompt：海报文字错位重影
    "img_prompt_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="420" height="560" viewBox="0 0 420 560">
<rect width="420" height="560" fill="#fdf3e7"/>
<rect x="30" y="30" width="360" height="500" rx="10" fill="#fff" stroke="#d8c3a5" stroke-width="4"/>
<rect x="60" y="60" width="300" height="60" fill="#c96f4a"/>
<text x="90" y="100" font-size="30" fill="#fff" font-family="sans-serif" font-weight="bold">AI 活动</text>
<text x="90" y="132" font-size="20" fill="#8a6f55" font-family="sans-serif">AI 活劫</text>
<text x="90" y="158" font-size="20" fill="#8a6f55" font-family="sans-serif">活动周</text>
<circle cx="330" cy="250" r="70" fill="#5a8f7b"/>
<circle cx="330" cy="250" r="45" fill="#7fb29a"/>
<text x="120" y="300" font-size="18" fill="#5a4a3a" font-family="sans-serif">时间：3 月 12 日</text>
<text x="120" y="330" font-size="18" fill="#5a4a3a" font-family="sans-serif">时间：3 月 21 日</text>
<text x="120" y="380" font-size="16" fill="#a08a70" font-family="sans-serif">地点：报告厅 101</text>
<text x="120" y="410" font-size="16" fill="#a08a70" font-family="sans-serif">地点：报厅 101</text>
<text x="120" y="460" font-size="14" fill="#a08a70" font-family="sans-serif">欢迎扫码报名</text>
</svg>""",
    # prompt：钟表指针矛盾（镜像）
    "img_prompt_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">
<rect width="420" height="420" fill="#eef1f5"/>
<circle cx="210" cy="210" r="160" fill="#fff" stroke="#3a4a5a" stroke-width="8"/>
<g stroke="#3a4a5a" stroke-width="6">
<line x1="210" y1="70" x2="210" y2="95"/><line x1="210" y1="325" x2="210" y2="350"/>
<line x1="70" y1="210" x2="95" y2="210"/><line x1="325" y1="210" x2="350" y2="210"/>
<line x1="91" y1="111" x2="108" y2="128"/><line x1="312" y1="292" x2="329" y2="309"/>
<line x1="329" y1="111" x2="312" y2="128"/><line x1="108" y1="292" x2="91" y2="309"/>
</g>
<line x1="210" y1="210" x2="210" y2="105" stroke="#c0392b" stroke-width="10" stroke-linecap="round"/>
<line x1="210" y1="210" x2="300" y2="260" stroke="#2c3e50" stroke-width="8" stroke-linecap="round"/>
<circle cx="210" cy="210" r="12" fill="#2c3e50"/>
<text x="160" y="395" font-size="14" fill="#7a8794" font-family="sans-serif">钟表特写</text>
</svg>""",
    # prompt：书本悬浮桌面
    "img_prompt_303.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="420" viewBox="0 0 560 420">
<rect width="560" height="420" fill="#f5f0e8"/>
<rect x="0" y="340" width="560" height="80" fill="#8a6f52"/>
<rect x="120" y="180" width="180" height="130" rx="6" fill="#3a6ea5" stroke="#2c5580" stroke-width="4"/>
<rect x="140" y="200" width="140" height="8" fill="#d9cba8"/>
<rect x="140" y="220" width="140" height="8" fill="#d9cba8"/>
<rect x="140" y="240" width="140" height="8" fill="#d9cba8"/>
<rect x="300" y="120" width="180" height="130" rx="6" fill="#a56a3a" stroke="#8a522c" stroke-width="4"/>
<rect x="320" y="140" width="140" height="8" fill="#ecd9b8"/>
<rect x="320" y="160" width="140" height="8" fill="#ecd9b8"/>
<rect x="320" y="180" width="140" height="8" fill="#ecd9b8"/>
<text x="200" y="400" font-size="14" fill="#6a5848" font-family="sans-serif">书桌一角</text>
</svg>""",
    # tools：图表坐标轴错乱
    "img_tools_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<rect width="560" height="400" fill="#fafbfc"/>
<line x1="70" y1="320" x2="520" y2="320" stroke="#3a4a5a" stroke-width="3"/>
<line x1="70" y1="60" x2="70" y2="320" stroke="#3a4a5a" stroke-width="3"/>
<g fill="#5a6a7a" font-family="sans-serif" font-size="13">
<text x="30" y="320">0</text><text x="30" y="255">100</text><text x="24" y="190">300</text><text x="24" y="125">200</text><text x="30" y="60">400</text>
</g>
<g fill="#7a8794" font-family="sans-serif" font-size="13">
<text x="110" y="345">1月</text><text x="200" y="345">2月</text><text x="290" y="345">3月</text><text x="380" y="345">4月</text><text x="470" y="345">5月</text>
</g>
<g fill="#3a8fb0"><rect x="100" y="255" width="50" height="65"/><rect x="190" y="190" width="50" height="130"/><rect x="280" y="280" width="50" height="40"/><rect x="370" y="125" width="50" height="195"/><rect x="460" y="220" width="50" height="100"/></g>
<line x1="70" y1="320" x2="520" y2="90" stroke="#c0392b" stroke-width="3" stroke-dasharray="6 4"/>
<text x="300" y="70" font-size="14" fill="#3a4a5a" font-family="sans-serif">季度销量趋势</text>
</svg>""",
    # tools：桌面物品透视矛盾
    "img_tools_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<rect width="560" height="400" fill="#efe9df"/>
<rect x="0" y="280" width="560" height="120" fill="#b99a72"/>
<rect x="80" y="200" width="200" height="80" rx="8" fill="#3a4a5a"/>
<rect x="100" y="215" width="160" height="10" fill="#7a8a9a"/>
<rect x="300" y="170" width="120" height="110" rx="6" fill="#c0392b"/>
<rect x="320" y="190" width="80" height="70" fill="#e8b88a"/>
<circle cx="180" cy="330" r="28" fill="#6a5a4a"/>
<rect x="420" y="250" width="80" height="30" rx="6" fill="#3a8fb0"/>
<rect x="420" y="250" width="80" height="15" rx="6" fill="#2c6f8a"/>
<text x="210" y="385" font-size="14" fill="#6a5848" font-family="sans-serif">办公桌面</text>
</svg>""",
    # tools：二维码缺定位角
    "img_tools_303.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="440" viewBox="0 0 400 440">
<rect width="400" height="440" fill="#f5f6f8"/>
<rect x="60" y="80" width="280" height="280" fill="#fff" stroke="#2c3e50" stroke-width="4"/>
<g fill="#2c3e50">
<rect x="80" y="100" width="70" height="70"/><rect x="95" y="115" width="40" height="40" fill="#fff"/><rect x="110" y="130" width="10" height="10"/>
<rect x="250" y="100" width="70" height="70"/><rect x="265" y="115" width="40" height="40" fill="#fff"/><rect x="280" y="130" width="10" height="10"/>
</g>
<g fill="#2c3e50">
<rect x="120" y="200" width="20" height="20"/><rect x="160" y="200" width="20" height="20"/><rect x="200" y="240" width="20" height="20"/><rect x="120" y="280" width="20" height="20"/><rect x="240" y="280" width="20" height="20"/><rect x="160" y="320" width="20" height="20"/><rect x="200" y="320" width="20" height="20"/><rect x="280" y="320" width="20" height="20"/>
<rect x="120" y="120" width="20" height="20"/><rect x="200" y="120" width="20" height="20"/><rect x="240" y="160" width="20" height="20"/><rect x="280" y="200" width="20" height="20"/><rect x="160" y="240" width="20" height="20"/><rect x="280" y="240" width="20" height="20"/><rect x="240" y="320" width="20" height="20"/>
</g>
<text x="140" y="405" font-size="14" fill="#7a8794" font-family="sans-serif">扫码报名二维码</text>
</svg>""",
    # evaluation：合影人数与倒影不一致
    "img_evaluation_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="420" viewBox="0 0 560 420">
<rect width="560" height="420" fill="#dce8f2"/>
<rect x="0" y="300" width="560" height="120" fill="#7a9bb8"/>
<g>
<circle cx="120" cy="200" r="26" fill="#e8b88a"/><rect x="95" y="226" width="50" height="70" rx="8" fill="#4a6a8a"/>
<circle cx="210" cy="190" r="28" fill="#e0a878"/><rect x="183" y="218" width="54" height="78" rx="8" fill="#8a5a3a"/>
<circle cx="300" cy="200" r="26" fill="#e8b88a"/><rect x="275" y="226" width="50" height="70" rx="8" fill="#4a6a8a"/>
<circle cx="390" cy="195" r="27" fill="#e0a878"/><rect x="364" y="222" width="52" height="74" rx="8" fill="#6a4a7a"/>
<circle cx="460" cy="205" r="24" fill="#e8b88a"/><rect x="438" y="229" width="44" height="67" rx="8" fill="#3a6a5a"/>
</g>
<rect x="60" y="310" width="440" height="8" fill="#4a6a8a" opacity="0.4"/>
<g opacity="0.35" fill="#4a6a8a">
<circle cx="120" cy="340" r="26"/><rect x="95" y="366" width="50" height="60"/>
<circle cx="210" cy="335" r="28"/><rect x="183" y="363" width="54" height="63"/>
<circle cx="300" cy="340" r="26"/><rect x="275" y="366" width="50" height="60"/>
<circle cx="390" cy="338" r="27"/><rect x="364" y="365" width="52" height="61"/>
</g>
<text x="200" y="55" font-size="15" fill="#3a4a5a" font-family="sans-serif">社团合影</text>
</svg>""",
    # evaluation：增长箭头与数据矛盾
    "img_evaluation_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<rect width="560" height="400" fill="#fbfcfd"/>
<line x1="80" y1="320" x2="520" y2="320" stroke="#3a4a5a" stroke-width="3"/>
<line x1="80" y1="60" x2="80" y2="320" stroke="#3a4a5a" stroke-width="3"/>
<g fill="#3a8fb0"><rect x="120" y="150" width="60" height="170"/><rect x="220" y="200" width="60" height="120"/><rect x="320" y="240" width="60" height="80"/><rect x="420" y="270" width="60" height="50"/></g>
<g fill="#5a6a7a" font-family="sans-serif" font-size="13">
<text x="135" y="345">Q1</text><text x="235" y="345">Q2</text><text x="335" y="345">Q3</text><text x="435" y="345">Q4</text>
</g>
<path d="M140 130 L300 90" stroke="#c0392b" stroke-width="6" fill="none" marker-end="url(#arrow)"/>
<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0 0 L12 6 L0 12 z" fill="#c0392b"/></marker></defs>
<text x="260" y="70" font-size="14" fill="#3a4a5a" font-family="sans-serif">年度销量：呈持续上升趋势</text>
</svg>""",
    # collaboration：两人影子方向相反
    "img_collaboration_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<rect width="560" height="400" fill="#f0eadf"/>
<rect x="0" y="300" width="560" height="100" fill="#c9b08c"/>
<rect x="60" y="80" width="440" height="220" rx="10" fill="#fff" stroke="#a89270" stroke-width="4"/>
<rect x="90" y="110" width="180" height="120" rx="8" fill="#3a6ea5"/>
<rect x="300" y="110" width="170" height="120" rx="8" fill="#a56a3a"/>
<circle cx="170" cy="250" r="22" fill="#e8b88a"/><rect x="150" y="272" width="40" height="55" rx="8" fill="#4a6a8a"/>
<circle cx="390" cy="250" r="22" fill="#e0a878"/><rect x="370" y="272" width="40" height="55" rx="8" fill="#8a5a3a"/>
<ellipse cx="160" cy="340" rx="34" ry="10" fill="#6a5848" opacity="0.4"/>
<ellipse cx="420" cy="340" rx="34" ry="10" fill="#6a5848" opacity="0.4"/>
<text x="200" y="380" font-size="14" fill="#6a5848" font-family="sans-serif">会议室讨论</text>
</svg>""",
    # collaboration：流程图箭头循环矛盾
    "img_collaboration_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="360" viewBox="0 0 560 360">
<rect width="560" height="360" fill="#f7f8fa"/>
<g stroke="#3a4a5a" stroke-width="3" fill="#fff" font-family="sans-serif" font-size="14">
<rect x="40" y="60" width="120" height="50" rx="8"/><text x="62" y="92">收集需求</text>
<rect x="220" y="60" width="120" height="50" rx="8"/><text x="242" y="92">AI 处理</text>
<rect x="400" y="60" width="120" height="50" rx="8"/><text x="422" y="92">人工审核</text>
<rect x="220" y="200" width="120" height="50" rx="8"/><text x="248" y="232">结果发布</text>
</g>
<g stroke="#c0392b" stroke-width="4" fill="none">
<line x1="160" y1="85" x2="218" y2="85"/>
<line x1="340" y1="85" x2="398" y2="85"/>
<path d="M400 110 L400 150 L340 150 L340 198"/>
<path d="M220 110 L220 150 L280 150 L280 198"/>
<path d="M340 225 L520 225 L520 30 L160 30 L160 58"/>
</g>
<g fill="#c0392b" font-family="sans-serif" font-size="12">
<text x="170" y="45">返回修改</text>
</g>
<text x="180" y="330" font-size="14" fill="#5a6a7a" font-family="sans-serif">AI 协作审批流程图</text>
</svg>""",
    # collaboration：桌面两个键盘
    "img_collaboration_303.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<rect width="560" height="400" fill="#ece6db"/>
<rect x="0" y="280" width="560" height="120" fill="#b08d62"/>
<rect x="100" y="180" width="180" height="100" rx="10" fill="#2c3e50"/>
<g fill="#5a6a7a"><rect x="115" y="195" width="18" height="14"/><rect x="140" y="195" width="18" height="14"/><rect x="165" y="195" width="18" height="14"/><rect x="190" y="195" width="18" height="14"/><rect x="215" y="195" width="18" height="14"/><rect x="115" y="216" width="18" height="14"/><rect x="140" y="216" width="18" height="14"/><rect x="165" y="216" width="18" height="14"/><rect x="190" y="216" width="18" height="14"/><rect x="215" y="216" width="18" height="14"/><rect x="115" y="237" width="18" height="14"/><rect x="140" y="237" width="18" height="14"/><rect x="165" y="237" width="18" height="14"/><rect x="190" y="237" width="18" height="14"/><rect x="215" y="237" width="18" height="14"/></g>
<rect x="330" y="180" width="180" height="100" rx="10" fill="#3a4a5a"/>
<g fill="#7a8a9a"><rect x="345" y="195" width="18" height="14"/><rect x="370" y="195" width="18" height="14"/><rect x="395" y="195" width="18" height="14"/><rect x="420" y="195" width="18" height="14"/><rect x="445" y="195" width="18" height="14"/><rect x="345" y="216" width="18" height="14"/><rect x="370" y="216" width="18" height="14"/><rect x="395" y="216" width="18" height="14"/><rect x="420" y="216" width="18" height="14"/><rect x="445" y="216" width="18" height="14"/><rect x="345" y="237" width="18" height="14"/><rect x="370" y="237" width="18" height="14"/><rect x="395" y="237" width="18" height="14"/><rect x="420" y="237" width="18" height="14"/><rect x="445" y="237" width="18" height="14"/></g>
<text x="210" y="380" font-size="14" fill="#6a5848" font-family="sans-serif">双人协作工位</text>
</svg>""",
    # ethics：证件照信息遮挡模糊
    "img_ethics_301.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="420" height="560" viewBox="0 0 420 560">
<rect width="420" height="560" fill="#f2f4f7"/>
<rect x="50" y="40" width="320" height="460" rx="10" fill="#fff" stroke="#b8c2cc" stroke-width="3"/>
<text x="120" y="90" font-size="16" fill="#3a4a5a" font-family="sans-serif">学员证</text>
<circle cx="210" cy="190" r="60" fill="#e8b88a"/>
<rect x="180" y="250" width="60" height="50" rx="8" fill="#4a6a8a"/>
<rect x="90" y="330" width="240" height="26" fill="#e2e6eb"/>
<rect x="90" y="375" width="240" height="26" fill="#e2e6eb"/>
<rect x="90" y="420" width="160" height="26" fill="#e2e6eb"/>
<rect x="100" y="336" width="90" height="14" fill="#c3ccd6"/>
<rect x="150" y="381" width="120" height="14" fill="#c3ccd6"/>
<rect x="140" y="426" width="60" height="14" fill="#c3ccd6"/>
<text x="120" y="530" font-size="14" fill="#7a8794" font-family="sans-serif">证件示例</text>
</svg>""",
    # ethics：监控画面光源与影子矛盾
    "img_ethics_302.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="560" height="360" viewBox="0 0 560 360">
<rect width="560" height="360" fill="#2a3444"/>
<rect x="0" y="280" width="560" height="80" fill="#1c2330"/>
<circle cx="80" cy="80" r="40" fill="#f6d876"/>
<rect x="0" y="0" width="560" height="14" fill="#0e1420"/>
<text x="20" y="30" font-size="12" fill="#8fa0b8" font-family="sans-serif">CAM-01</text>
<g>
<circle cx="380" cy="230" r="22" fill="#7a8aa0"/><rect x="362" y="252" width="36" height="50" rx="6" fill="#3a4a5a"/>
</g>
<ellipse cx="500" cy="300" rx="40" ry="10" fill="#0e1420" opacity="0.6"/>
<rect x="470" y="120" width="6" height="170" fill="#5a6a7a"/>
<circle cx="473" cy="112" r="8" fill="#f6d876"/>
<text x="200" y="340" font-size="13" fill="#8fa0b8" font-family="sans-serif">走廊监控画面</text>
</svg>""",
    # ethics：对话截图日期矛盾
    "img_ethics_303.svg": """<svg xmlns="http://www.w3.org/2000/svg" width="520" height="480" viewBox="0 0 520 480">
<rect width="520" height="480" fill="#eef1f5"/>
<rect x="40" y="30" width="440" height="420" rx="12" fill="#fff" stroke="#c9d2db" stroke-width="3"/>
<text x="150" y="75" font-size="16" fill="#3a4a5a" font-family="sans-serif">群聊：项目推进</text>
<text x="60" y="120" font-size="13" fill="#8a97a5" font-family="sans-serif">2026年3月15日</text>
<rect x="60" y="135" width="300" height="54" rx="10" fill="#eef1f5"/><text x="80" y="160" font-size="14" fill="#3a4a5a" font-family="sans-serif">张三：明天提交初稿</text><text x="80" y="182" font-size="13" fill="#8a97a5" font-family="sans-serif">10:02</text>
<rect x="160" y="205" width="300" height="54" rx="10" fill="#dce9f7"/><text x="180" y="230" font-size="14" fill="#2c4a6a" font-family="sans-serif">李四：收到，今天完成</text><text x="180" y="252" font-size="13" fill="#8a97a5" font-family="sans-serif">10:05</text>
<text x="60" y="290" font-size="13" fill="#8a97a5" font-family="sans-serif">2025年12月1日</text>
<rect x="60" y="305" width="300" height="54" rx="10" fill="#eef1f5"/><text x="80" y="330" font-size="14" fill="#3a4a5a" font-family="sans-serif">王五：初稿已提交</text><text x="80" y="352" font-size="13" fill="#8a97a5" font-family="sans-serif">09:30</text>
<text x="150" y="420" font-size="13" fill="#8a97a5" font-family="sans-serif">以上为聊天记录截图示例</text>
</svg>""",
}

for name, content in SVGS.items():
    (OUT / name).write_text(content.strip(), encoding="utf-8")
    print("generated", name)
print(f"\nTotal: {len(SVGS)} SVG assets -> {OUT}")
