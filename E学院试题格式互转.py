# -*- coding: utf-8 -*-
"""
E学院试题格式互转工具
=====================
在「旧版试题格式（.doc，文件名带 _2023）」与「新版试题格式（.doc，文件名带 _2026）」之间互相转换。

旧版特征：
    * 题干 + A/B/C/D 选项 + 「正确答案：ABCD」或「【答案】D」+「【难度】一般」
    * 全部题目混排，没有题型分节
    * 判断题答案写在题干末尾，如「……处分。（正确）」

新版特征：
    * 按题型分节：【单选题开始】……【单选题结束】/【多选题开始】/【判断题开始】
    * 答案统一写成「正确答案：X」
    * 引号等符号使用 HTML 实体（&ldquo; &rdquo; &lsquo; &rsquo; &mdash;）

作者：WorkBuddy
"""

import os
import re
import html
import shutil
import tempfile
import traceback

# ============================================================================
# 常量
# ============================================================================

OPT_LETTERS = "ABCDEFGH"
JUDGE_TRUE = ("正确", "√", "对", "T", "TRUE", "是")
JUDGE_FALSE = ("错误", "×", "错", "F", "FALSE", "否")

DIR_AUTO = "auto"          # 自动识别
DIR_TO_NEW = "to_new"      # 旧版 -> 新版
DIR_TO_OLD = "to_old"      # 新版 -> 旧版

FMT_OLD = "old"            # 旧版格式标识
FMT_NEW = "new"            # 新版格式标识

TAG_OLD = "_2023"
TAG_NEW = "_2026"

SECTION_NAMES = {"single": "单选题", "multi": "多选题", "judge": "判断题"}
TYPE_ORDER = ("single", "multi", "judge")

# 新版里会出现的 HTML 实体
ENTITY_OUT = [
    ("\u201c", "&ldquo;"),   # “
    ("\u201d", "&rdquo;"),   # ”
    ("\u2018", "&lsquo;"),   # ‘
    ("\u2019", "&rsquo;"),   # ’
    ("\u2014", "&mdash;"),   # —
]

# ============================================================================
# 正则
# ============================================================================

RE_SECTION = re.compile(r"^[【\[]\s*(单选题|多选题|判断题|单选|多选|判断)\s*(开始|结束|始|终)\s*[】\]]\s*$")
RE_QNO = re.compile(r"^\s*(\d{1,4})\s*[、.．,，)）]\s*(.*)$")
RE_OPT = re.compile(r"^\s*([A-Ha-h])\s*[.．、,，:：]\s*(.*)$")
RE_ANS_BRACKET = re.compile(
    r"^\s*[【\[]\s*(?:正确答案|参考答案|答案|正确答案是)\s*[】\]]\s*[：:、.]?\s*(.+?)\s*$")
RE_ANS_PLAIN = re.compile(
    r"^\s*(?:正确答案|参考答案|标准答案|答案)\s*[：:]\s*(.+?)\s*$")
RE_DIFF = re.compile(r"^\s*[【\[]\s*难度\s*[】\]]\s*(.*?)\s*$")
RE_INLINE_JUDGE = re.compile(r"[（(]\s*(正确|错误|√|×|对|错)\s*[)）]\s*[。.]?\s*$")
RE_ESC = re.compile(r"[\u201c\u201d\u2018\u2019\u2014]")
RE_TAIL_PUNCT = re.compile(r"[。．.；;，,、\s]+$")


# ============================================================================
# 文本工具
# ============================================================================


def normalize_text(raw: str) -> str:
    """统一换行、去不可见字符、把 Word 的特殊段落符换成换行。"""
    if not raw:
        return ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\x0b", "\n").replace("\x0c", "\n")   # 手动换行符 / 分页符
    raw = raw.replace("\x07", "\n")                          # 表格单元格结束符
    raw = raw.replace("\u00a0", " ").replace("\u3000", " ")  # 不间断空格 / 全角空格
    raw = raw.replace("\ufeff", "")
    raw = raw.replace("\x00", "")
    return raw


def unescape_entities(text: str) -> str:
    """把 &ldquo; 之类的实体还原成普通字符。"""
    if not text or "&" not in text:
        return text
    try:
        return html.unescape(text)
    except Exception:
        return text


def escape_entities(text: str) -> str:
    """把“”‘’— 转成新版使用的 HTML 实体（先还原，避免重复转义）。"""
    if not text:
        return text
    text = unescape_entities(text)
    for ch, ent in ENTITY_OUT:
        text = text.replace(ch, ent)
    return text


def join_parts(parts) -> str:
    """把折行后的多段文字拼回一行：中文直接相连，英文/数字之间补空格。"""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", p):
            out += " " + p
        else:
            out += p
    return out.strip()


def is_judge_value(value: str):
    """把答案文本判定为 正确 / 错误 / None。"""
    if not value:
        return None
    v = value.strip().strip("。.；;")
    v = v.strip("（）()【】[] ")
    up = v.upper()
    if up in JUDGE_TRUE:
        return "正确"
    if up in JUDGE_FALSE:
        return "错误"
    return None


# ============================================================================
# 数据模型
# ============================================================================


class Question:
    """一道题。"""

    def __init__(self, no):
        self.no = no
        self.stem_parts = []
        self.options = []          # [(字母, 文本)]
        self.answer = ""           # "D" / "ABCD" / "正确" / "错误" / ""
        self.difficulty = ""
        self.section = ""          # 源文件中的分节：single/multi/judge
        self.qtype = ""            # single/multi/judge
        self.notes = []            # 校验提示

    # -- 解析结果整理 ------------------------------------------------------
    @property
    def stem(self):
        return join_parts(self.stem_parts)

    def set_stem(self, text):
        self.stem_parts = [text] if text else []

    @property
    def is_judge(self):
        return self.qtype == "judge"

    @property
    def inline_judge(self):
        """题干末尾的（正确）/（错误）标记。"""
        m = RE_INLINE_JUDGE.search(self.stem)
        return is_judge_value(m.group(1)) if m else None

    def finalize(self):
        """推断题型、清洗答案、生成校验提示。"""
        self.stem_parts = [join_parts(self.stem_parts)] if self.stem_parts else []

        # 1. 判断题
        inline = self.inline_judge
        ans_judge = is_judge_value(self.answer)
        if not self.options and (inline or ans_judge):
            self.qtype = "judge"
            if not self.answer and inline:
                self.answer = inline
            if self.answer:
                self.answer = is_judge_value(self.answer) or self.answer
            self._normalize_judge_mark(inline or ans_judge)
            return

        # 2. 有选项 -> 单选 / 多选
        if self.options:
            letters = re.sub(r"[^A-H]", "", (self.answer or "").upper())
            self.answer = letters
            if not letters:
                self.qtype = "multi" if self.section == "multi" else "single"
                self.notes.append("缺少答案")
            else:
                self.qtype = "multi" if len(letters) > 1 else "single"
                if self.section and self.section != self.qtype:
                    self.notes.append("题型与分节不符（按答案字母数判定）")
                illegal = [c for c in letters if c not in [o[0] for o in self.options]]
                if illegal:
                    self.notes.append("答案字母 %s 无对应选项" % "".join(illegal))
        else:
            # 既无选项也无数值型答案：按分节或答案字面判断
            if self.section == "judge" or ans_judge:
                self.qtype = "judge"
                self.answer = ans_judge or self.answer
                self._normalize_judge_mark(ans_judge or self.inline_judge)
            else:
                self.qtype = "single"
                self.notes.append("既无选项也无答案")
        if self.qtype == "judge" and not self.answer:
            self.notes.append("缺少判断题答案")

    def _normalize_judge_mark(self, mark):
        """把题干末尾的（ 正确 ）统一成（正确），缺失则补上。"""
        if not mark:
            return
        stem = self.stem
        if RE_INLINE_JUDGE.search(stem):
            stem = RE_INLINE_JUDGE.sub("（%s）" % mark, stem)
        else:
            stem = stem.rstrip() + "（%s）" % mark
        self.set_stem(stem)


# ============================================================================
# 解析
# ============================================================================


def detect_format(raw: str) -> str:
    """判断文本属于旧版还是新版格式，返回 FMT_OLD / FMT_NEW。"""
    text = normalize_text(raw)
    if re.search(r"[【\[]\s*(单选题|多选题|判断题|多选|判断|单选)", text):
        return FMT_NEW
    return FMT_OLD


def parse_exam_text(raw: str):
    """把试题文本解析成 Question 列表。

    返回 (questions, warnings)
    """
    text = normalize_text(raw)
    raw_lines = text.split("\n")

    questions = []
    warnings = []
    cur = None
    section = ""
    expect_no = 1
    last_no = 0
    prev_was_answer = False   # 上一行是否为答案/难度行

    def close_current():
        nonlocal cur
        if cur is not None:
            cur.finalize()
            questions.append(cur)
            cur = None

    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue

        # 1) 分节标记
        m = RE_SECTION.match(line)
        if m:
            name, flag = m.group(1), m.group(2)
            close_current()
            if flag in ("结束", "终"):
                section = ""
            else:
                section = {"单选": "single", "多选": "multi",
                           "判断": "judge"}.get(name.replace("题", ""), "")
            prev_was_answer = True
            continue

        # 2) 题目起始行
        m = RE_QNO.match(line)
        if m:
            no = int(m.group(1))
            body = m.group(2)
            # 只有在顺序对得上、或上一行是答案行时才认为是新题
            if (cur is None) or (no == last_no + 1) or (no == expect_no) or prev_was_answer:
                # 排除 “A.某选项” 这类被 RE_QNO 误判的情况：数字编号一般不会接字母选项
                if not (cur is not None and cur.options and not prev_was_answer and no < last_no):
                    close_current()
                    cur = Question(no)
                    cur.section = section
                    last_no = no
                    expect_no = no + 1
                    prev_was_answer = False
                    if body:
                        cur.stem_parts.append(body)
                    continue

        if cur is None:
            # 头部说明文字，忽略
            if line and not warnings:
                warnings.append("开头存在未归属文字，已忽略：%s" % line[:40])
            continue

        # 3) 答案行
        m = RE_ANS_BRACKET.match(line) or RE_ANS_PLAIN.match(line)
        if m:
            val = m.group(1).strip()
            # 少数文件把难度写在答案同一行，这里拆开
            dm = re.search(r"[【\[]\s*难度\s*[】\]]\s*(.*)$", val)
            if dm:
                cur.difficulty = dm.group(1).strip() or "一般"
                val = val[: dm.start()].strip()
            if not cur.answer:
                cur.answer = val
            else:
                cur.notes.append("出现多个答案，已取第一个")
            prev_was_answer = True
            continue

        # 4) 难度行
        m = RE_DIFF.match(line)
        if m:
            cur.difficulty = m.group(1).strip() or "一般"
            prev_was_answer = True
            continue

        # 5) 选项行
        m = RE_OPT.match(line)
        if m and not prev_was_answer:
            letter = m.group(1).upper()
            # 选项字母必须按 A、B、C…… 递增，否则视为正文
            expect_letter = OPT_LETTERS[len(cur.options)] if len(cur.options) < len(OPT_LETTERS) else ""
            if letter == expect_letter and (cur.options or cur.stem_parts):
                cur.options.append([letter, m.group(2).strip()])
                continue

        # 6) 续行
        if cur.options and not cur.answer:
            cur.options[-1][1] = join_parts([cur.options[-1][1], line])
        else:
            cur.stem_parts.append(line)
        prev_was_answer = False

    close_current()

    # 统一成纯字符串选项
    for q in questions:
        q.options = [(l, t) for l, t in q.options]
        # 题干里去掉残留的答案实体
        if q.stem:
            q.stem_parts = [unescape_entities(q.stem)]

    if not questions:
        warnings.append("未解析到任何题目，请检查文件内容是否符合试题格式")

    return questions, warnings


# ============================================================================
# 生成文本
# ============================================================================


def _answer_label(qtype, style):
    """旧版答案标签风格。"""
    if style == "bracket":
        return "【答案】"
    if style == "correct":
        return "正确答案："
    # auto：单选沿用旧文件习惯用【答案】，多选用正确答案：
    return "【答案】" if qtype == "single" else "正确答案："


def build_lines(questions, target, options=None):
    """把题目渲染成目标格式的文本行。

    target: FMT_NEW / FMT_OLD
    options: dict(regroup=bool, answer_style='auto'/'correct'/'bracket',
                  with_difficulty=bool)
    """
    options = options or {}
    regroup = options.get("regroup", True)
    answer_style = options.get("answer_style", "auto")
    with_difficulty = options.get("with_difficulty", True)

    to_new = (target == FMT_NEW)

    items = list(questions)
    if to_new and regroup:
        order = {t: i for i, t in enumerate(TYPE_ORDER)}
        items = [q for _i, q in sorted(
            enumerate(items), key=lambda pair: (order.get(pair[1].qtype, 9), pair[0]))]

    lines = []
    cur_section = None

    for idx, q in enumerate(items, start=1):
        if to_new:
            if q.qtype != cur_section:
                if cur_section:
                    lines.append("【%s结束】" % SECTION_NAMES[cur_section])
                    lines.append("")
                cur_section = q.qtype
                lines.append("【%s开始】" % SECTION_NAMES[cur_section])
            elif lines and lines[-1] != "":
                lines.append("")

        stem = escape_entities(q.stem) if to_new else unescape_entities(q.stem)
        if q.qtype == "judge":
            mark = q.inline_judge or is_judge_value(q.answer)
            if mark and not RE_INLINE_JUDGE.search(stem):
                stem = stem.rstrip() + "（%s）" % mark
        lines.append("%d、%s" % (idx, stem))

        for letter, otext in q.options:
            t = escape_entities(otext) if to_new else unescape_entities(otext)
            lines.append("%s.%s" % (letter, t))

        if q.qtype != "judge" and q.answer:
            label = "正确答案：" if to_new else _answer_label(q.qtype, answer_style)
            lines.append("%s%s" % (label, q.answer))

        if with_difficulty:
            lines.append("【难度】%s" % (q.difficulty or "一般"))

        if not to_new:
            lines.append("")

    # 收尾
    if to_new and cur_section:
        lines.append("【%s结束】" % SECTION_NAMES[cur_section])
    if to_new:
        # 题目之间空一行
        merged = []
        for ln in lines:
            if ln == "" and merged and merged[-1] == "":
                continue
            merged.append(ln)
        lines = merged

    while lines and lines[-1] == "":
        lines.pop()
    return lines


def summarize(questions):
    """统计 + 校验信息。"""
    stat = {"single": 0, "multi": 0, "judge": 0}
    issues = []
    for i, q in enumerate(questions, start=1):
        stat[q.qtype] = stat.get(q.qtype, 0) + 1
        for note in q.notes:
            issues.append("第 %d 题（原题号 %s）：%s" % (i, q.no, note))
    return stat, issues


# ============================================================================
# 文档读写（.doc / .docx / .txt）
# ============================================================================

WD_FORMAT_DOCUMENT = 0


class WordBridge:
    """通过 COM 调用 Word / WPS 读写 .doc。

    Word 在关闭最后一个文档后可能自行退出，因此在实例中保留一份空白
    “保活文档”；若进程仍意外退出，则自动重建连接并重试一次。
    """

    def __init__(self, log=None):
        self._app = None
        self._keeper = None
        self._prog = ""
        self._log = log or (lambda *a, **k: None)
        self._failed = False

    # -- 连接管理 ----------------------------------------------------------
    def app(self):
        if self._app is not None and self._alive():
            return self._app
        self._reset()
        if self._failed:
            return None
        try:
            import win32com.client as win32
        except Exception:
            self._failed = True
            self._log("未安装 pywin32，无法使用 Word 引擎处理 .doc")
            return None
        for prog in ("Word.Application", "KWPS.Application"):
            try:
                app = win32.DispatchEx(prog)
                try:
                    app.Visible = False
                except Exception:
                    pass
                try:
                    app.DisplayAlerts = 0
                except Exception:
                    pass
                self._app = app
                self._prog = prog
                try:
                    self._keeper = app.Documents.Add()   # 保活，防止 Word 空载退出
                except Exception:
                    self._keeper = None
                self._log("已连接文档引擎：%s" % prog)
                return app
            except Exception:
                continue
        self._failed = True
        self._log("未检测到可用的 Word / WPS，将改用纯文本方式处理")
        return None

    def _alive(self):
        try:
            _ = self._app.Version
            return True
        except Exception:
            return False

    def _reset(self):
        if self._keeper is not None:
            try:
                self._keeper.Close(0)
            except Exception:
                pass
            self._keeper = None
        if self._app is not None:
            try:
                self._app.Quit()
            except Exception:
                pass
            self._app = None

    def _open(self, path, readonly):
        """打开文档，失败时自动重建连接再试一次。"""
        for attempt in range(2):
            app = self.app()
            if app is None:
                return None
            try:
                return app.Documents.Open(os.path.abspath(path), False, bool(readonly), False)
            except Exception as exc:
                self._log("打开文档失败（第 %d 次）：%s" % (attempt + 1, exc))
                self._reset()
        return None

    # -- 读写 --------------------------------------------------------------
    def read_text(self, path):
        doc = self._open(path, True)
        if doc is None:
            return None
        try:
            return normalize_text(doc.Content.Text)
        except Exception as exc:
            self._log("读取文档内容失败：%s" % exc)
            return None
        finally:
            try:
                doc.Close(0)
            except Exception:
                pass

    def docx_to_doc(self, docx_path, doc_path):
        doc = self._open(docx_path, False)
        if doc is None:
            return False
        try:
            try:
                doc.SaveAs2(os.path.abspath(doc_path), WD_FORMAT_DOCUMENT)
            except Exception:
                doc.SaveAs(os.path.abspath(doc_path), WD_FORMAT_DOCUMENT)
            return os.path.exists(doc_path)
        except Exception as exc:
            self._log("转换为 .doc 失败：%s" % exc)
            return False
        finally:
            try:
                doc.Close(0)
            except Exception:
                pass

    def close(self):
        self._reset()


def _looks_like_zip(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except Exception:
        return False


def _read_docx(path):
    from docx import Document
    doc = Document(path)
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    lines = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            lines.append(Paragraph(child, doc).text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    lines.extend(paragraph.text for paragraph in cell.paragraphs)
    return "\n".join(lines)


def _read_plain(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def read_document(path, bridge: WordBridge = None):
    """读取文档正文。返回 (text, 引擎说明)"""
    ext = os.path.splitext(path)[1].lower()

    if ext in (".txt", ".md"):
        return _read_plain(path), "纯文本"

    if ext == ".docx":
        try:
            return _read_docx(path), "python-docx"
        except Exception as exc:
            raise RuntimeError("无法读取 DOCX 文档，请确认文件未损坏且当前环境已安装 python-docx：%s"
                               % exc) from exc

    if _looks_like_zip(path):
        try:
            return _read_docx(path), "python-docx"
        except Exception as exc:
            raise RuntimeError("无法读取 DOCX 文档，请确认文件未损坏且当前环境已安装 python-docx：%s"
                               % exc) from exc

    if bridge is None:
        raise RuntimeError("读取 .doc 文件需要 Microsoft Word 或 WPS 文档引擎")
    text = bridge.read_text(path)
    if text is not None and text.strip():
        return text, "Word 引擎"

    try:
        text = _read_plain(path)
        if text.strip():
            return text, "纯文本兜底"
    except Exception:
        pass

    raise RuntimeError("无法读取文件内容（可能不是有效的 Word 文档）")


def lines_to_docx(lines, docx_path):
    """把文本行写成排版好的 .docx。"""
    from docx import Document
    from docx.shared import Pt
    from docx.oxml.ns import qn

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(12)          # 小四
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.5

    for line in lines:
        para = doc.add_paragraph()
        if line:
            para.add_run(line)
    doc.save(docx_path)


def write_document(lines, out_path, bridge: WordBridge = None):
    """写出 .doc 或 .docx，返回文档引擎说明。"""
    extension = os.path.splitext(out_path)[1].lower()
    if extension == ".docx":
        lines_to_docx(lines, out_path)
        return "python-docx"
    if extension != ".doc":
        raise ValueError("输出文件必须使用 .doc 或 .docx 扩展名")
    if bridge is None:
        raise ValueError("导出 .doc 需要 WordBridge 文档引擎")

    tmpdir = tempfile.mkdtemp(prefix="exam_doc_")
    docx_path = os.path.join(tmpdir, "tmp.docx")
    try:
        lines_to_docx(lines, docx_path)
        if bridge.docx_to_doc(docx_path, out_path) and os.path.exists(out_path):
            return "Word 引擎"
        raise RuntimeError("无法导出 .doc，请安装并配置 Microsoft Word 或 WPS。")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# 转换流水线
# ============================================================================


def decide_direction(text, direction):
    """返回 (源格式, 目标格式, 输出文件名后缀)。

    输出文件名后缀跟随目标格式：旧版题库尾加 _2023，新版题库尾加 _2026。
    """
    src = detect_format(text)
    if direction == DIR_TO_NEW:
        tgt = FMT_NEW
    elif direction == DIR_TO_OLD:
        tgt = FMT_OLD
    else:                                   # 自动：互转
        tgt = FMT_OLD if src == FMT_NEW else FMT_NEW
    tag = TAG_OLD if tgt == FMT_OLD else TAG_NEW
    return src, tgt, tag


def base_name_for(src_path):
    """源文件名去掉已有的 _2023/_2026 等后缀，作为输出文件的主名。"""
    base = os.path.splitext(os.path.basename(src_path))[0]
    for t in ("_2023", "_2026", "-2023", "-2026", "（2023）", "（2026）"):
        if base.endswith(t):
            base = base[: -len(t)]
    return base.strip() or "试卷"


def output_path_for(src_path, tag, out_dir=None, extension=".doc"):
    """算出输出路径：原文件名（去掉旧后缀）+ 目标后缀和指定扩展名。"""
    extension = extension.lower()
    if extension not in (".doc", ".docx"):
        raise ValueError("输出文件格式必须是 .doc 或 .docx")
    name = base_name_for(src_path) + tag
    folder = out_dir or os.path.dirname(os.path.abspath(src_path))
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name + extension)
    renamed = False
    idx = 1
    while os.path.exists(target):
        target = os.path.join(folder, "%s(%d)%s" % (name, idx, extension))
        idx += 1
        renamed = True
    return target, renamed


def convert_text(raw, direction, options=None):
    """文本 -> (目标文本行, 统计, 问题列表, 源格式)"""
    src_fmt, tgt_fmt, _tag = decide_direction(raw, direction)
    questions, warnings = parse_exam_text(raw)
    lines = build_lines(questions, tgt_fmt, options)
    stat, issues = summarize(questions)
    return lines, stat, warnings + issues, src_fmt


def convert_file(src_path, direction, out_dir=None, options=None, bridge=None, log=None,
                 output_format=".doc"):
    """转换单个文件，返回 (输出路径, 统计, 提示列表)"""
    log = log or (lambda *a, **k: None)
    output_format = output_format.lower()
    if output_format not in (".doc", ".docx"):
        raise ValueError("输出文件格式必须是 .doc 或 .docx")
    source_ext = os.path.splitext(src_path)[1].lower()
    own_bridge = bridge is None and (
        source_ext not in (".docx", ".txt", ".md") or output_format == ".doc")
    if own_bridge:
        bridge = WordBridge(log)
    try:
        raw, engine = read_document(src_path, bridge)
        src_fmt, tgt_fmt, tag = decide_direction(raw, direction)
        questions, warnings = parse_exam_text(raw)
        if not questions:
            raise RuntimeError("未能解析出题目，请检查文件内容")
        lines = build_lines(questions, tgt_fmt, options)
        stat, issues = summarize(questions)
        out_path, renamed = output_path_for(src_path, tag, out_dir, output_format)
        if renamed:
            issues.append("输出目录已有同名文件，已自动改名为 %s（不覆盖原稿）"
                          % os.path.basename(out_path))
        wengine = write_document(lines, out_path, bridge)
        return out_path, stat, warnings + issues, engine, wengine
    finally:
        if own_bridge:
            bridge.close()


# ============================================================================
# 图形界面（PyQt6 优先，自动兼容 PyQt5）
# ============================================================================

QT_API = None
try:                                        # 首选 PyQt6（对 Python 3.12+ 支持最好）
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
    from PyQt6.QtGui import QFont, QTextCursor
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QPushButton, QLabel, QListWidget, QListWidgetItem, QGroupBox, QComboBox,
        QCheckBox, QLineEdit, QFileDialog, QMessageBox, QSplitter, QPlainTextEdit,
        QAbstractItemView, QProgressBar,
    )
    QT_API = 6
except ImportError:                         # 退回 PyQt5
    try:
        from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings
        from PyQt5.QtGui import QFont, QTextCursor
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
            QPushButton, QLabel, QListWidget, QListWidgetItem, QGroupBox, QComboBox,
            QCheckBox, QLineEdit, QFileDialog, QMessageBox, QSplitter, QPlainTextEdit,
            QAbstractItemView, QProgressBar,
        )
        QT_API = 5
    except ImportError:
        QT_API = None


def run_gui():
    import sys

    if QT_API is None:
        raise RuntimeError("未找到 PyQt6 / PyQt5 运行库，请先执行：\n    pip install PyQt6")

    # 兼容 PyQt5 / PyQt6 的枚举取值
    if QT_API == 6:
        H_ORIENT = Qt.Orientation.Horizontal
        ROLE_USER = Qt.ItemDataRole.UserRole
        WRAP_MODE = QPlainTextEdit.LineWrapMode.WidgetWidth
        CUR_START = QTextCursor.MoveOperation.Start
    else:
        H_ORIENT = Qt.Horizontal
        ROLE_USER = Qt.UserRole
        WRAP_MODE = QPlainTextEdit.WidgetWidth
        CUR_START = QTextCursor.Start
    SEL_EXT = QAbstractItemView.SelectionMode.ExtendedSelection if QT_API == 6 \
        else QAbstractItemView.ExtendedSelection

    ACCEPT_EXT = (".doc", ".docx", ".txt", ".wps")

    class Worker(QThread):
        """后台批量转换线程，避免界面卡死。"""
        log_sig = pyqtSignal(str)
        done_sig = pyqtSignal(int, int)

        def __init__(self, files, direction, out_dir, options, output_format):
            super().__init__()
            self.files = files
            self.direction = direction
            self.out_dir = out_dir
            self.options = options
            self.output_format = output_format

        def run(self):
            ok = fail = 0
            bridge = WordBridge(self.log_sig.emit)
            try:
                for i, path in enumerate(self.files, start=1):
                    self.log_sig.emit("[%d/%d] 正在转换：%s"
                                      % (i, len(self.files), os.path.basename(path)))
                    try:
                        out_path, stat, issues, engine, wengine = convert_file(
                            path, self.direction, self.out_dir, self.options, bridge,
                            self.log_sig.emit, self.output_format)
                        self.log_sig.emit(
                            "    ✔ 已生成：%s  （单选 %d / 多选 %d / 判断 %d，读取 %s，写出 %s）"
                            % (os.path.basename(out_path), stat["single"], stat["multi"],
                               stat["judge"], engine, wengine))
                        for msg in issues[:5]:
                            self.log_sig.emit("    ! " + msg)
                        if len(issues) > 5:
                            self.log_sig.emit("    ! 另有 %d 条提示未显示" % (len(issues) - 5))
                        ok += 1
                    except Exception as exc:
                        fail += 1
                        self.log_sig.emit("    ✘ 失败：%s" % exc)
                        self.log_sig.emit("      " + traceback.format_exc().strip().split("\n")[-1])
            finally:
                bridge.close()
            self.done_sig.emit(ok, fail)

    class DropList(QListWidget):
        """支持拖入文件的列表。"""
        filesDropped = pyqtSignal(list)

        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.setSelectionMode(SEL_EXT)

        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event):
            paths = []
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if os.path.isdir(p):
                    paths += [os.path.join(p, f) for f in sorted(os.listdir(p))
                              if f.lower().endswith(ACCEPT_EXT)]
                elif p.lower().endswith(ACCEPT_EXT):
                    paths.append(p)
            if paths:
                self.filesDropped.emit(paths)
            event.acceptProposedAction()

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("E学院试题格式互转工具  v1.0")
            self.resize(1200, 780)
            self.setAcceptDrops(True)
            self.settings = QSettings("WorkBuddy", "EExamConverter")
            self.worker = None
            self._bridge = None     # 预览用文档引擎（复用，避免反复启动 Word）

            self._build_ui()
            self._load_settings()

        # ---------------- 界面搭建 ----------------
        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QHBoxLayout(central)
            root.setContentsMargins(12, 12, 12, 12)
            root.setSpacing(10)

            splitter = QSplitter(H_ORIENT)
            root.addWidget(splitter)

            # ---- 左栏 ----
            left = QWidget()
            lv = QVBoxLayout(left)
            lv.setContentsMargins(0, 0, 0, 0)
            lv.setSpacing(8)

            box_files = QGroupBox("① 待转换文件（可直接拖入，支持批量）")
            bf = QVBoxLayout(box_files)
            self.list_files = DropList()
            self.list_files.filesDropped.connect(self.add_files)
            self.list_files.currentItemChanged.connect(self.on_select)
            bf.addWidget(self.list_files)

            row = QHBoxLayout()
            btn_add = QPushButton("添加文件")
            btn_addfolder = QPushButton("添加文件夹")
            btn_del = QPushButton("移除选中")
            btn_clear = QPushButton("清空")
            for b in (btn_add, btn_addfolder, btn_del, btn_clear):
                row.addWidget(b)
            bf.addLayout(row)
            btn_add.clicked.connect(self.pick_files)
            btn_addfolder.clicked.connect(self.pick_folder)
            btn_del.clicked.connect(self.remove_selected)
            btn_clear.clicked.connect(self.clear_files)

            box_set = QGroupBox("② 转换设置")
            gs = QGridLayout(box_set)
            gs.setVerticalSpacing(6)
            gs.addWidget(QLabel("转换方向"), 0, 0)
            self.cmb_dir = QComboBox()
            self.cmb_dir.addItem("自动识别（旧版→新版 _2026 / 新版→旧版 _2023）", DIR_AUTO)
            self.cmb_dir.addItem("旧版 _2023  →  新版 _2026", DIR_TO_NEW)
            self.cmb_dir.addItem("新版 _2026  →  旧版 _2023", DIR_TO_OLD)
            gs.addWidget(self.cmb_dir, 0, 1, 1, 3)

            gs.addWidget(QLabel("答案标注"), 1, 0)
            self.cmb_ans = QComboBox()
            self.cmb_ans.addItem("自动（单选【答案】/ 多选正确答案：）", "auto")
            self.cmb_ans.addItem("统一使用「正确答案：」", "correct")
            self.cmb_ans.addItem("统一使用「【答案】」", "bracket")
            gs.addWidget(self.cmb_ans, 1, 1, 1, 3)

            self.chk_regroup = QCheckBox("转新版时按题型分组排序（单选→多选→判断）")
            self.chk_regroup.setChecked(True)
            gs.addWidget(self.chk_regroup, 2, 0, 1, 4)

            self.chk_diff = QCheckBox("保留【难度】行（源文件缺失时补「一般」）")
            self.chk_diff.setChecked(True)
            gs.addWidget(self.chk_diff, 3, 0, 1, 4)

            gs.addWidget(QLabel("导出格式"), 4, 0)
            self.cmb_format = QComboBox()
            self.cmb_format.addItem("DOCX（无需 Word/WPS）", ".docx")
            self.cmb_format.addItem("DOC（需要 Word/WPS）", ".doc")
            gs.addWidget(self.cmb_format, 4, 1, 1, 3)

            gs.addWidget(QLabel("输出目录"), 5, 0)
            self.ed_out = QLineEdit()
            self.ed_out.setPlaceholderText("留空则输出到源文件所在目录")
            gs.addWidget(self.ed_out, 5, 1)
            btn_out = QPushButton("浏览")
            btn_out.setFixedWidth(56)
            btn_out.clicked.connect(self.pick_outdir)
            gs.addWidget(btn_out, 5, 2)
            btn_open = QPushButton("打开")
            btn_open.setFixedWidth(56)
            btn_open.setToolTip("在资源管理器中打开输出目录")
            btn_open.clicked.connect(self.open_outdir)
            gs.addWidget(btn_open, 5, 3)

            btn_row = QHBoxLayout()
            btn_help = QPushButton("说明")
            btn_help.setFixedWidth(56)
            btn_help.clicked.connect(self.show_help)
            self.btn_preview = QPushButton("预览转换结果")
            self.btn_run = QPushButton("开始转换并导出文件")
            self.btn_run.setMinimumHeight(38)
            self.btn_run.setStyleSheet(
                "QPushButton{background:#2f6fdd;color:#fff;border-radius:6px;font-weight:600;}"
                "QPushButton:hover{background:#3b7cf0;}"
                "QPushButton:disabled{background:#9db8e6;}")
            btn_row.addWidget(btn_help)
            btn_row.addWidget(self.btn_preview)
            btn_row.addWidget(self.btn_run, 1)
            self.btn_preview.clicked.connect(self.do_preview)
            self.btn_run.clicked.connect(self.do_convert)

            self.progress = QProgressBar()
            self.progress.setVisible(False)

            lv.addWidget(box_files, 1)
            lv.addWidget(box_set)
            lv.addLayout(btn_row)
            lv.addWidget(self.progress)

            # ---- 右栏 ----
            right = QWidget()
            rv = QVBoxLayout(right)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(6)

            head = QHBoxLayout()
            head.addWidget(QLabel("③ 转换结果预览"))
            head.addStretch(1)
            self.lbl_stat = QLabel("尚未载入文件")
            self.lbl_stat.setStyleSheet("color:#666;")
            head.addWidget(self.lbl_stat)
            rv.addLayout(head)

            f = QFont("Microsoft YaHei")
            f.setPointSize(10)
            self.txt_preview = QPlainTextEdit()
            self.txt_preview.setReadOnly(True)
            self.txt_preview.setLineWrapMode(WRAP_MODE)
            self.txt_preview.setFont(f)
            rv.addWidget(self.txt_preview, 3)

            rv.addWidget(QLabel("④ 运行日志"))
            self.txt_log = QPlainTextEdit()
            self.txt_log.setReadOnly(True)
            self.txt_log.setMaximumBlockCount(5000)
            self.txt_log.setFont(f)
            self.txt_log.setStyleSheet("background:#fafafa;")
            rv.addWidget(self.txt_log, 1)

            splitter.addWidget(left)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([470, 720])

            self.statusBar().showMessage("提示：把 .doc 文件直接拖进窗口即可")

        # ---------------- 文件管理 ----------------
        def add_files(self, paths):
            exist = {self.list_files.item(i).data(ROLE_USER)
                     for i in range(self.list_files.count())}
            added = 0
            for p in paths:
                if not os.path.isfile(p) or p in exist:
                    continue
                item = QListWidgetItem(os.path.basename(p))
                item.setData(ROLE_USER, p)
                item.setToolTip(p)
                self.list_files.addItem(item)
                exist.add(p)
                added += 1
            if added:
                self.log("已添加 %d 个文件" % added)
                if self.list_files.count() == added:
                    self.list_files.setCurrentRow(0)
            else:
                self.log("没有新增文件（重复或格式不支持）")

        def pick_files(self):
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择试题文件", "", "Word 文档 (*.doc *.docx *.wps);;所有文件 (*.*)")
            if files:
                self.add_files(files)

        def pick_folder(self):
            folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
            if not folder:
                return
            paths = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                     if f.lower().endswith(ACCEPT_EXT)]
            self.add_files(paths)

        def pick_outdir(self):
            folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
            if folder:
                self.ed_out.setText(os.path.normpath(folder))

        def open_outdir(self):
            folder = self.ed_out.text().strip()
            if not folder:
                item = self.list_files.currentItem()
                if item is None:
                    QMessageBox.information(self, "提示", "未指定输出目录时，结果与源文件放在一起")
                    return
                folder = os.path.dirname(item.data(ROLE_USER))
            if os.path.isdir(folder):
                os.startfile(folder)
            else:
                QMessageBox.information(self, "提示", "目录不存在：%s" % folder)

        def remove_selected(self):
            for item in self.list_files.selectedItems():
                self.list_files.takeItem(self.list_files.row(item))

        def clear_files(self):
            self.list_files.clear()
            self.txt_preview.clear()
            self.lbl_stat.setText("尚未载入文件")

        def files(self):
            return [self.list_files.item(i).data(ROLE_USER)
                    for i in range(self.list_files.count())]

        # ---------------- 预览 ----------------
        def on_select(self, current, previous):
            if current is not None:
                self.preview(current.data(ROLE_USER))

        def do_preview(self):
            item = self.list_files.currentItem()
            if item is None and self.list_files.count():
                item = self.list_files.item(0)
            if item is None:
                QMessageBox.information(self, "提示", "请先添加待转换的文件")
                return
            self.preview(item.data(ROLE_USER))

        def preview(self, path):
            if self._bridge is None:
                self._bridge = WordBridge(self.log)
            try:
                raw, engine = read_document(path, self._bridge)
                direction = self.cmb_dir.currentData()
                lines, stat, issues, src_fmt = convert_text(raw, direction, self._options())
                _, tgt_fmt, tag = decide_direction(raw, direction)
                self.txt_preview.setPlainText("\n".join(lines))
                self.txt_preview.moveCursor(CUR_START)
                src_txt = "新版" if src_fmt == FMT_NEW else "旧版"
                tgt_txt = "新版" if tgt_fmt == FMT_NEW else "旧版"
                info = "源：%s → 目标：%s ｜ 单选 %d / 多选 %d / 判断 %d ｜ 读取引擎：%s" % (
                    src_txt, tgt_txt, stat["single"], stat["multi"], stat["judge"], engine)
                if issues:
                    info += " ｜ 提示 %d 条" % len(issues)
                self.lbl_stat.setText(info)
                self.log("预览：%s（%s）" % (os.path.basename(path), engine))
                extension = self.cmb_format.currentData()
                self.log("  将导出为：%s%s（内容为%s格式）"
                         % (base_name_for(path) + tag, extension, tgt_txt))
                for msg in issues[:20]:
                    self.log("  ! " + msg)
            except Exception as exc:
                self.txt_preview.setPlainText("预览失败：%s" % exc)
                self.lbl_stat.setText("预览失败")
                self.log("预览失败：%s" % exc)

        # ---------------- 转换 ----------------
        def _options(self):
            return {
                "regroup": self.chk_regroup.isChecked(),
                "answer_style": self.cmb_ans.currentData(),
                "with_difficulty": self.chk_diff.isChecked(),
            }

        def do_convert(self):
            files = self.files()
            if not files:
                QMessageBox.information(self, "提示", "请先添加待转换的文件")
                return
            if self.worker is not None and self.worker.isRunning():
                return
            self._save_settings()
            self.log("=" * 60)
            self.log("开始批量转换，共 %d 个文件" % len(files))
            self.btn_run.setEnabled(False)
            self.btn_preview.setEnabled(False)
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)          # 忙碌动画

            self.worker = Worker(files, self.cmb_dir.currentData(),
                                 self.ed_out.text().strip() or None, self._options(),
                                 self.cmb_format.currentData())
            self.worker.log_sig.connect(self.log)
            self.worker.done_sig.connect(self.on_done)
            self.worker.start()

        def on_done(self, ok, fail):
            self.progress.setVisible(False)
            self.btn_run.setEnabled(True)
            self.btn_preview.setEnabled(True)
            self.log("转换结束：成功 %d 个，失败 %d 个" % (ok, fail))
            self.statusBar().showMessage("转换结束：成功 %d 个，失败 %d 个" % (ok, fail))
            if fail == 0:
                QMessageBox.information(self, "完成", "全部转换成功：%d 个文件" % ok)
            else:
                QMessageBox.warning(self, "完成", "成功 %d 个，失败 %d 个，请查看日志" % (ok, fail))

        # ---------------- 杂项 ----------------
        def show_help(self):
            QMessageBox.information(self, "使用说明", (
                "1. 把旧版（文件名带 _2023）或新版（_2026）的 .doc/.docx 拖进左侧列表，可批量添加。\n"
                "2. 「转换方向」选自动识别即可：旧版转新版并命名为 _2026，新版转旧版并命名为 _2023。\n"
                "3. 可在「导出格式」选择 DOC 或 DOCX；DOCX 无需安装 Word/WPS。\n"
                "4. 点「预览转换结果」核对内容与题量统计，再点「开始转换并导出文件」。\n"
                "5. 导出文件名后缀跟随题目版本：\n"
                "   旧版格式尾加 _2023，新版格式尾加 _2026；\n"
                "   若已有同名文件会自动加序号，不会覆盖原稿。\n\n"
                "转换规则：\n"
                "· 转新版：按题型分组（单选→多选→判断），加【单选题开始】等分节标记，\n"
                "  答案统一写成「正确答案：X」；\n"
                "· 转旧版：去掉分节标记，判断题答案保留在题干末尾的（正确）/（错误）；\n"
                "· 新版里的引号等符号是 HTML 实体形式，转旧版时会还原成正常字符；\n"
                "· 日志区会列出缺答案、答案字母与选项数不符等可疑题，供人工复核。\n\n"
                "依赖：DOCX 使用 python-docx；DOC 读写需要 Microsoft Word 或 WPS。"
            ))

        def log(self, text):
            self.txt_log.appendPlainText(text)

        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dropEvent(self, event):
            paths = []
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if os.path.isdir(p):
                    paths += [os.path.join(p, f) for f in sorted(os.listdir(p))
                              if f.lower().endswith(ACCEPT_EXT)]
                elif p.lower().endswith(ACCEPT_EXT):
                    paths.append(p)
            if paths:
                self.add_files(paths)
            event.acceptProposedAction()

        def _load_settings(self):
            try:
                self.cmb_dir.setCurrentIndex(int(self.settings.value("dir_idx", 0)))
                self.cmb_ans.setCurrentIndex(int(self.settings.value("ans_idx", 0)))
                self.cmb_format.setCurrentIndex(int(self.settings.value("format_idx", 0)))
                self.chk_regroup.setChecked(self.settings.value("regroup", True, type=bool))
                self.chk_diff.setChecked(self.settings.value("diff", True, type=bool))
                out = self.settings.value("out_dir", "", type=str)
                if out:
                    self.ed_out.setText(out)
            except Exception:
                pass

        def _save_settings(self):
            try:
                self.settings.setValue("dir_idx", self.cmb_dir.currentIndex())
                self.settings.setValue("ans_idx", self.cmb_ans.currentIndex())
                self.settings.setValue("format_idx", self.cmb_format.currentIndex())
                self.settings.setValue("regroup", self.chk_regroup.isChecked())
                self.settings.setValue("diff", self.chk_diff.isChecked())
                self.settings.setValue("out_dir", self.ed_out.text().strip())
            except Exception:
                pass

        def closeEvent(self, event):
            if self._bridge is not None:
                self._bridge.close()
                self._bridge = None
            if self.worker is not None and self.worker.isRunning():
                self.worker.wait(3000)
            self._save_settings()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei")
    font.setPointSize(9)
    app.setFont(font)
    win = MainWindow()
    win.show()
    win.log("就绪。旧版文件（_2023）与新文件（_2026）均可直接拖入。")
    win.log("界面框架：PyQt%d" % QT_API)
    code = app.exec() if hasattr(app, "exec") else app.exec_()
    sys.exit(code)


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        _err = traceback.format_exc()
        try:
            _log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "错误日志.txt")
            with open(_log, "a", encoding="utf-8") as _fh:
                _fh.write(_err + "\n" + "-" * 60 + "\n")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, _err[-1200:], "E学院试题格式互转工具 - 启动失败", 0x10)
        except Exception:
            print(_err)
