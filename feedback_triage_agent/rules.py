from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Dict, Iterator, List, Optional, Tuple

from feedback_triage_agent.models import ClassifiedFeedback, FeedbackRecord


REQUIRED_FIELDS = ["id", "source", "app_name", "review_text", "rating"]

ISSUE_CATEGORIES = [
    "模型能力问题",
    "交互体验问题",
    "性能与稳定性问题",
    "会员与商业化问题",
    "内容安全与合规问题",
    "账号、隐私与数据问题",
    "用户预期与产品定位问题",
    "正向反馈/无明确问题",
    "不明确/其他",
]

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "模型能力问题": [
        "答非所问",
        "不准确",
        "幻觉",
        "编造",
        "理解错",
        "识别错",
        "回答错",
        "错了",
        "算错",
        "搞错",
        "瞎编",
        "骗人",
        "事实",
        "对错",
        "错误率",
        "识别不准",
        "识别错误",
        "语音识别差",
        "语音识别没",
        "不能生成",
        "模型",
        "翻译",
        "总结",
        "推荐不准",
        "不懂",
        "错误答案",
        "wrong answer",
        "incorrect answer",
        "wrong response",
        "incorrect response",
        "wrong information",
        "wrong facts",
        "gets things wrong",
        "get things wrong",
        "inaccurate",
        "hallucination",
        "hallucinate",
        "made up facts",
        "makes up facts",
        "does not understand",
        "doesn't understand",
        "did not understand",
        "misunderstands",
        "does not follow instructions",
        "doesn't follow instructions",
        "did not follow instructions",
        "not following instructions",
        "ignores instructions",
        "ignored instructions",
        "not doing what i say",
        "does not do what i say",
        "doesn't do what i say",
        "not relevant",
        "irrelevant",
        "cannot trust",
        "can't trust",
        "bad memory",
        "does not remember",
        "doesn't remember",
        "keeps forgetting",
        "forget what",
        "repeating the same",
        "repeats the same",
        "same mistakes",
        "stupid results",
        "dumb ai",
        "bad translation",
        "translation is wrong",
        "image generator",
        "image generation",
    ],
    "交互体验问题": [
        "不好用",
        "难用",
        "按钮",
        "搜索按钮",
        "按钮不见",
        "入口",
        "界面",
        "交互",
        "操作",
        "找不到",
        "提示不清",
        "流程",
        "输入框",
        "复制",
        "保存",
        "夜间模式",
        "hard to use",
        "difficult to use",
        "confusing interface",
        "user interface",
        "navigation",
        "button",
        "cannot find",
        "can't find",
        "could not find",
        "input box",
        "copy",
        "save",
        "dark mode",
        "upload button",
        "read aloud",
        "option disappears",
        "button disappears",
    ],
    "性能与稳定性问题": [
        "卡",
        "慢",
        "延迟",
        "崩溃",
        "闪退",
        "加载",
        "无响应",
        "断开",
        "失败",
        "报错",
        "打不开",
        "卡住",
        "转圈",
        "没反应",
        "算力不足",
        "服务器繁忙",
        "高峰期",
        "任务暂停",
        "暂停",
        "内存已满",
        "内存满",
        "速度慢",
        "very slow",
        "too slow",
        "slow response",
        "responds slowly",
        "slow",
        "laggy",
        "lagging",
        "crash",
        "crashes",
        "crashed",
        "crashing",
        "hangs",
        "hanging",
        "freezing",
        "freezes",
        "frozen",
        "unresponsive",
        "not responding",
        "disconnects",
        "disconnected",
        "failed to load",
        "loading forever",
        "does not work",
        "doesn't work",
        "not working",
        "stopped working",
        "error",
        "bug",
        "bugs",
        "cannot open",
        "can't open",
        "won't open",
        "timeout",
        "takes too long",
        "taking too long",
        "try again",
        "keeps failing",
        "cannot send",
        "can't send",
        "not sending",
    ],
    "会员与商业化问题": [
        "会员",
        "订阅",
        "付费",
        "扣费",
        "价格",
        "退款",
        "广告",
        "权益",
        "套餐",
        "试用",
        "收费",
        "消息数量",
        "对话限制",
        "次数限制",
        "额度限制",
        "上传限制",
        "subscription",
        "subscribe",
        "charged",
        "charging",
        "payment",
        "price",
        "expensive",
        "refund",
        "premium",
        "upgrade to plus",
        "pay for",
        "paywall",
        "image limit",
        "message limit",
        "usage limit",
        "daily limit",
        "too many ads",
        "advertisement",
        "not affordable",
        "cannot afford",
        "can't afford",
        "restriction",
        "too many limits",
        "too much limits",
        "everything is limited",
        "upload limit",
        "free version",
        "upgrade",
        "asking for money",
        "pay money",
        "only allows",
        "picture uploads",
        "photo uploads",
    ],
    "内容安全与合规问题": [
        "违规",
        "色情",
        "暴力",
        "仇恨",
        "辱骂",
        "不安全",
        "敏感",
        "未成年",
        "违法",
        "内容安全",
        "审核",
        "unsafe content",
        "harmful content",
        "sexual content",
        "explicit content",
        "violence",
        "violent",
        "hate speech",
        "abusive",
        "illegal",
        "minors",
        "child safety",
        "promoting war",
        "promotes war",
    ],
    "账号、隐私与数据问题": [
        "登录",
        "账号",
        "隐私",
        "泄露",
        "手机号",
        "数据丢失",
        "聊天记录",
        "找回",
        "密码",
        "注销",
        "权限",
        "同步",
        "客户资料",
        "login",
        "log in",
        "sign in",
        "account",
        "privacy",
        "data leak",
        "phone number",
        "lost data",
        "data loss",
        "chat history",
        "conversation history",
        "password",
        "delete account",
        "account deletion",
        "permission",
        "sync",
        "synchronization",
        "hacked account",
        "account hacked",
        "sign up",
        "signup",
        "shares data",
        "shared my data",
        "deleted my",
        "delete my",
        "dialogue deleted",
        "response deleted",
    ],
    "用户预期与产品定位问题": [
        "以为",
        "希望",
        "能不能",
        "应该",
        "不如",
        "期待",
        "定位",
        "适合",
        "场景",
        "办公",
        "学习",
        "建议官方",
        "希望官方",
        "希望能修复",
        "希望能增加",
        "增加一个",
        "支持团队",
        "产品",
        "边界",
        "please add",
        "add a feature",
        "feature request",
        "i wish",
        "i hope",
        "should have",
        "needs a",
        "need a",
        "would be great",
        "could you add",
        "want a",
        "expected",
        "expectation",
        "use case",
        "for work",
        "for studying",
        "memory feature",
        "please work on",
        "i want",
        "please make",
    ],
}

P0_KEYWORDS = [
    "崩溃",
    "闪退",
    "内容丢失",
    "数据丢失",
    "隐私泄露",
    "泄露",
    "扣费",
    "支付失败",
    "退款",
    "投诉",
    "卸载",
    "再也不用",
    "封号",
    "账号被盗",
    "丢了",
    "丢失",
    "误扣",
    "自动扣费",
    "crash",
    "crashes",
    "crashed",
    "crashing",
    "data loss",
    "lost data",
    "privacy leak",
    "unauthorized charge",
    "charged without permission",
    "payment failed",
    "refund",
    "uninstall",
    "never use again",
    "hacked account",
    "account hacked",
]

P1_KEYWORDS = [
    "很慢",
    "卡",
    "失败",
    "打不开",
    "无法",
    "不能",
    "严重影响",
    "影响使用",
    "核心",
    "报错",
    "错误",
    "不准",
    "不准确",
    "答非所问",
    "找不到",
    "同步失败",
    "转圈",
    "没反应",
    "算力不足",
    "服务器繁忙",
    "速度慢",
    "very slow",
    "too slow",
    "laggy",
    "lagging",
    "failed",
    "cannot use",
    "can't use",
    "does not work",
    "doesn't work",
    "not working",
    "error",
    "inaccurate",
    "wrong answer",
    "wrong information",
    "cannot find",
    "can't find",
    "sync failed",
    "hangs",
    "hanging",
    "takes too long",
    "try again",
    "cannot send",
    "can't send",
]

POSITIVE_FEEDBACK_KEYWORDS = [
    "好用",
    "很好",
    "不错",
    "很棒",
    "优秀",
    "满意",
    "推荐",
    "挺好用",
    "帮助挺大",
    "超赞",
    "情绪价值",
    "还不错",
    "很喜欢",
    "良心",
    "强大",
    "惊艳",
    "聪明",
    "good",
    "nice",
    "great",
    "cool",
    "excellent",
    "awesome",
    "amazing",
    "best",
    "super",
    "superb",
    "perfect",
    "helpful",
    "useful",
    "very useful",
    "love it",
    "i love it",
    "love",
    "fantastic",
    "wonderful",
    "brilliant",
    "thank you",
    "thanks",
    "thank",
    "good app",
    "nice app",
    "great app",
    "best app",
    "good work",
    "good job",
    "works well",
    "easy to use",
    "very cool",
    "happy",
    "first class",
    "works great",
    "well done",
    "okay",
    "ok",
    "supar",
    "supper",
    "👍",
]

POSITIVE_CONTRAST_MARKERS = (
    "但是",
    "不过",
    "然而",
    "问题",
    "不好",
    "很差",
    " but ",
    "however",
    "although",
    "except",
    "problem",
    "issue",
    "bad",
    "poor",
    "worse",
    "worst",
)

USER_NEED_BY_CATEGORY = {
    "模型能力问题": "获得准确、稳定、符合上下文的 AI 输出。",
    "交互体验问题": "更低成本地完成核心操作，减少查找和理解成本。",
    "性能与稳定性问题": "在关键任务中获得快速、连续、可靠的使用体验。",
    "会员与商业化问题": "清楚理解付费权益、价格、扣费和退款规则。",
    "内容安全与合规问题": "避免不安全或不合规内容带来的产品和用户风险。",
    "账号、隐私与数据问题": "保护账号、隐私、历史内容和跨设备数据连续性。",
    "用户预期与产品定位问题": "确认产品适用场景、能力边界和可交付结果。",
    "正向反馈/无明确问题": "继续稳定获得当前产品价值，无需进入问题修复流程。",
    "不明确/其他": "需要补充上下文，澄清用户遇到的具体任务和阻塞点。",
}

SUGGESTION_BY_CATEGORY = {
    "模型能力问题": "沉淀高频失败样本，补充评测集，并在输出前增加事实性和上下文一致性检查。",
    "交互体验问题": "梳理用户完成任务的关键路径，优化入口、按钮文案和空状态提示。",
    "性能与稳定性问题": "优先复现异常链路，补充客户端日志、超时提示和失败后的恢复机制。",
    "会员与商业化问题": "核对权益判断和扣费链路，在付费前后提供清晰提醒、凭证和退款入口。",
    "内容安全与合规问题": "将样本加入安全评测集，强化生成前后的风险识别、拦截和申诉说明。",
    "账号、隐私与数据问题": "检查登录、同步和权限链路，明确数据保存策略，并提供可追踪的恢复流程。",
    "用户预期与产品定位问题": "在新手引导、模板和结果页说明能力边界，减少用户对交付形态的误解。",
    "正向反馈/无明确问题": "记录正向体验信号并用于趋势观察；当前样本不创建问题修复项。",
    "不明确/其他": "进入人工复核队列，补充来源、任务场景和用户期望后再决定产品动作。",
}

GENERIC_SUGGESTIONS = {"", "优化体验", "继续观察", "后续优化", "待确认"}
NEGATION_PREFIXES = (
    "没有",
    "未",
    "不",
    "无",
    "从未",
    "从来没有",
    "并未",
    "不会",
    "不再",
    "no",
    "not",
    "never",
    "without",
    "doesn't",
    "doesnt",
    "didn't",
    "didnt",
    "isn't",
    "isnt",
    "wasn't",
    "wasnt",
    "won't",
    "wont",
    "can't",
    "cant",
)
POSITIVE_RISK_CONTEXTS = {
    "退款": ("退款成功", "已退款", "退款很快", "顺利退款", "退款到账"),
    "refund": ("refund processed", "refund was quick", "got my refund"),
    "扣费": ("没有扣费", "未扣费", "不会扣费"),
    "charged": ("not charged", "never charged", "charged correctly"),
    "崩溃": ("没有崩溃", "从未崩溃", "不会崩溃"),
    "crash": ("no crash", "never crash", "doesn't crash", "does not crash"),
    "crashes": ("no crashes", "never crashes", "doesn't crash", "does not crash"),
    "闪退": ("没有闪退", "从未闪退", "不会闪退"),
}
POSITIVE_CATEGORY_CONTEXTS = {
    "加载": ("加载很快", "加载不慢", "加载也不慢", "加载正常", "加载流畅"),
    "slow": ("not slow", "isn't slow", "is not slow"),
}
CATEGORY_TIE_BREAK_ORDER = [
    "账号、隐私与数据问题",
    "会员与商业化问题",
    "内容安全与合规问题",
    "模型能力问题",
    "性能与稳定性问题",
    "交互体验问题",
    "用户预期与产品定位问题",
]


def normalize_for_matching(text: str) -> str:
    normalized = str(text).lower().replace("’", "'")
    return re.sub(r"\s+", " ", normalized).strip()


def compact_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text)))


def summarize_text(text: str, max_length: int = 42) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max_length]}..."


DATA_CATEGORY = "账号、隐私与数据问题"
CONTENT_LOSS_REASON = "疑似内容丢失、可恢复性待核查"
RECOVERED_LOSS_REASON = "历史内容丢失已恢复、恢复状态待确认"
CLAUSE_BREAK = re.compile(r"[，,。.!！？?；;\n]+|但是|不过|然而|可是|但|却")
DATA_OBJECT = re.compile(
    r"(?:聊天|对话|历史)(?:记录|历史)|草稿|文档|文件|笔记|日记|稿件|报告|记录|客户资料|资料|数据|内容"
    r"|(?:写|保存|存下).{0,10}?(?:东西|文字|稿子)"
    r"|\b(?:drafts?|documents?|notes?|files?|chat history|conversation history|data)\b"
)
LOSS_PREDICATE = re.compile(
    r"丢失(?:了|过)?|丢了|不见(?:了)?|消失(?:了)?|找不到(?:了)?|(?:全|都|全部)?没(?:有)?了"
    r"|(?:被)?清空(?:了)?|一片空白|不可见|看不到"
    r"|\b(?:disappeared|disappear|gone|lost|loss)\b"
)
RECOVERY = re.compile(
    r"(?:已经|已|后来)(?:成功)?(?:恢复|找回)|(?:找回|恢复)(?:了|成功|正常)"
    r"|\b(?:restored|recovered)\b"
)
LOSS_WORDS = {"内容丢失", "数据丢失", "丢失", "丢了", "lost data", "data loss"}
NON_DATA_OBJECT = re.compile(r"图片|按钮|入口|图标|上文|上下文|(?:模型|推理|分析|记忆)能力")


@dataclass(frozen=True)
class ContentLossEvent:
    start: int
    end: int
    object_name: str
    status: str  # reported, recovered, or excluded; never a confirmed incident


def _clauses(text: str) -> Iterator[Tuple[int, int, str]]:
    start = 0
    for boundary in CLAUSE_BREAK.finditer(text):
        if boundary.start() > start:
            yield start, boundary.start(), text[start:boundary.start()]
        start = boundary.end()
    if start < len(text):
        yield start, len(text), text[start:]


def content_loss_events(text: str) -> List[ContentLossEvent]:
    """Resolve object, local polarity/owner and subsequent recovery in report order.

    A missing button or a model's memory is not a persisted object. Object and
    ownership carry into adjacent clauses (e.g. 'my drafts, gone this morning'),
    while a newly named object or explicit target resets that context.
    """
    text = normalize_for_matching(text)
    events: List[ContentLossEvent] = []
    previous_object = ""
    foreign = False
    unsaved = False
    intentional = False
    for start, end, clause in _clauses(text):
        owners = list(re.finditer(
            r"(?P<foreign>竞品|别家|另一款|其他(?:软件|应用|产品)|\bcompetitor\b|\bother app\b)"
            r"|(?P<target>这款|本(?:产品|应用|软件)|\bthis app\b)", clause,
        ))
        if owners:
            foreign = owners[-1].lastgroup == "foreign"
        objects = list(DATA_OBJECT.finditer(clause))
        if objects and objects[0].group() != previous_object:
            unsaved = intentional = False
        if objects and re.search(r"(?:昨天|昨晚|刚|已|自动).{0,3}(?:保存|存下|写完|写好)", clause):
            unsaved = intentional = False
        unsaved = unsaved or bool(re.search(r"未保存|没(?:有)?(?:点)?保存|尚未保存|忘记保存|还没存", clause))
        deletion = re.search(r"(?:主动|手动)(?:删除|删掉|删过|清空)|(?:我|自己|本人).{0,8}(?:删除|删掉|清空)", clause)
        if deletion and not keyword_is_negated(clause, deletion.start()):
            intentional = True
        actions = [(m.start(), "loss", m) for m in LOSS_PREDICATE.finditer(clause)]
        actions += [(m.start(), "recovery", m) for m in RECOVERY.finditer(clause)]
        for _, kind, match in sorted(actions, key=lambda action: action[0]):
            preceding = [obj for obj in objects if obj.start() <= match.start()]
            obj = preceding[-1].group() if preceding else (objects[0].group() if objects else previous_object)
            if not obj:
                continue
            prefix = clause[:match.start()]
            # Generic content in a model-memory request is not stored user data.
            abstract = obj in {"内容", "数据"} and bool(re.search(r"上下文|上文|模型能力|记忆能力", clause))
            repeated_report = bool(re.search(r"每次|总是|经常|已经遇到|\bevery time\b", clause))
            hypothetical = (
                bool(re.search(r"如果|假如|万一|要是|\bif\b", prefix)) and not repeated_report
            ) or bool(re.search(r"(?:会|可能).{0,3}$", prefix) and re.search(r"吗|么|怎么办", clause))
            future_concern = bool(re.search(r"(?:将来|未来|以后).{0,8}(?:可能)?会|担心.{0,12}(?:可能)?会", prefix))
            hypothetical = hypothetical or (future_concern and not repeated_report)
            negated = keyword_is_negated(clause, match.start()) or prefix.rstrip().endswith(
                ("并非", "不是", "不曾", "未曾")
            )
            if kind == "recovery":
                if not foreign and not negated and not hypothetical and not re.search(r"希望|能否|想", prefix):
                    events = [
                        replace(event, status="recovered")
                        if event.object_name == obj and event.status == "reported" else event
                        for event in events
                    ]
                continue
            # A visible UI/image failure does not inherit a prior data noun.
            nearer_ui = [item for item in NON_DATA_OBJECT.finditer(prefix)]
            other_object = (
                bool(re.match(r"(?:的)?(?:图片|按钮|入口|图标|上文|上下文)", clause[match.end():]))
                or bool(nearer_ui and (not preceding or nearer_ui[-1].start() > preceding[-1].start()))
            )
            # A first lookup on an unsynced new device does not establish that
            # previously present records disappeared. Keep the existing sync
            # fault classification/review, rather than inventing storage loss.
            sync_lookup = (
                match.group().startswith(("找不到", "看不到", "不可见"))
                and obj in {"聊天记录", "历史记录", "对话记录"}
                and bool(re.search(r"换设备|新手机|新设备|另一台", text))
                and bool(re.search(r"同步失败|尚未同步|还没同步|未同步", text))
                and not re.search(r"刚|保存|写完|原来还在", clause)
            )
            excluded = (
                foreign or unsaved or intentional or abstract or hypothetical
                or negated or other_object or sync_lookup
            )
            events.append(ContentLossEvent(start, end, obj, "excluded" if excluded else "reported"))
        if objects:
            previous_object = objects[-1].group()
        elif NON_DATA_OBJECT.search(clause):
            previous_object = ""
    return events


def keyword_is_negated(text: str, start: int) -> bool:
    # A negated earlier clause does not negate the next independent event.
    boundaries = list(CLAUSE_BREAK.finditer(text, 0, start))
    left = boundaries[-1].end() if boundaries else 0
    prefix = text[max(left, start - 24) : start].rstrip()
    if any(phrase in prefix for phrase in ("没有", "未发生", "并未", "从未", "从来没有")):
        return True
    return any(prefix.endswith(negation) for negation in NEGATION_PREFIXES)


def keyword_has_positive_risk_context(text: str, keyword: str) -> bool:
    return any(phrase in text for phrase in POSITIVE_RISK_CONTEXTS.get(keyword, ()))


def keyword_has_positive_category_context(text: str, keyword: str) -> bool:
    return any(phrase in text for phrase in POSITIVE_CATEGORY_CONTEXTS.get(keyword, ()))


def contains_actionable_keyword(
    text: str,
    keyword: str,
    *,
    category_check: bool = False,
    priority_check: bool = False,
) -> bool:
    keyword_pattern = re.escape(keyword)
    if keyword and keyword[0].isascii() and keyword[0].isalnum():
        keyword_pattern = rf"(?<![a-z0-9]){keyword_pattern}(?![a-z0-9])"
    for match in re.finditer(keyword_pattern, text):
        start = match.start()
        if category_check and keyword in {"聊天记录", "chat history", "conversation history"} and any(
            event.status == "excluded" and event.start <= start < event.end
            for event in content_loss_events(text)
        ):
            continue
        if keyword in LOSS_WORDS and not any(
            event.status == "reported" and event.start <= start < event.end
            for event in content_loss_events(text)
        ):
            continue
        if not keyword_is_negated(text, start):
            local = next((clause for left, right, clause in _clauses(text) if left <= start < right), text)
            positive_category = category_check and keyword_has_positive_category_context(local, keyword)
            positive_risk = priority_check and keyword_has_positive_risk_context(local, keyword)
            if not positive_category and not positive_risk:
                return True
    return False


def remove_overlapping_hits(hits: List[str]) -> List[str]:
    selected: List[str] = []
    for keyword in sorted(hits, key=len, reverse=True):
        if not any(keyword in existing for existing in selected):
            selected.append(keyword)
    return [keyword for keyword in hits if keyword in selected]


def score_categories(text: str) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    normalized = normalize_for_matching(text)
    scores: Dict[str, int] = {}
    matched_keywords: Dict[str, List[str]] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = [
            keyword
            for keyword in keywords
            if contains_actionable_keyword(
                normalized,
                normalize_for_matching(keyword),
                category_check=True,
            )
        ]
        hits = remove_overlapping_hits(hits)
        scores[category] = len(hits)
        if hits:
            matched_keywords[category] = hits
    return scores, matched_keywords


def detect_positive_feedback(text: str, rating: Optional[int]) -> List[str]:
    if rating is not None and rating < 4:
        return []
    normalized = normalize_for_matching(text)
    if any(marker in normalized for marker in POSITIVE_CONTRAST_MARKERS):
        return []
    hits = [
        keyword
        for keyword in POSITIVE_FEEDBACK_KEYWORDS
        if contains_actionable_keyword(
            normalized,
            normalize_for_matching(keyword),
        )
    ]
    return remove_overlapping_hits(hits)


def pick_category(scores: Dict[str, int]) -> str:
    if not scores or max(scores.values()) == 0:
        return "不明确/其他"
    top_score = max(scores.values())
    winners = [category for category, score in scores.items() if score == top_score]
    return next(category for category in CATEGORY_TIE_BREAK_ORDER if category in winners)


def calculate_confidence(scores: Dict[str, int], matched_categories: List[str]) -> float:
    if not matched_categories:
        return 0.25
    ordered_scores = sorted(scores.values(), reverse=True)
    top_score = ordered_scores[0]
    second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0
    margin = top_score - second_score
    confidence = 0.55 + min(top_score, 4) * 0.08 + min(margin, 3) * 0.06
    if len(matched_categories) > 1:
        confidence -= 0.08
    return round(max(0.35, min(confidence, 0.95)), 2)


def determine_priority(text: str, rating: Optional[int]) -> str:
    normalized = normalize_for_matching(text)
    if any(event.status == "reported" for event in content_loss_events(normalized)):
        return "P0"
    if any(
        contains_actionable_keyword(
            normalized,
            normalize_for_matching(keyword),
            priority_check=True,
        )
        for keyword in P0_KEYWORDS
    ):
        return "P0"
    if rating is not None and rating <= 2:
        return "P1"
    if any(
        contains_actionable_keyword(
            normalized,
            normalize_for_matching(keyword),
            priority_check=True,
        )
        for keyword in P1_KEYWORDS
    ):
        return "P1"
    return "P2"


def build_issue_title(priority: str, category: str, summary: str) -> str:
    compact_summary = summary if len(summary) <= 20 else f"{summary[:20]}..."
    return f"{priority} {category}：{compact_summary}"


def is_product_suggestion_too_generic(suggestion: str) -> bool:
    normalized = suggestion.strip()
    return normalized in GENERIC_SUGGESTIONS or len(normalized) < 10


def build_product_suggestion(text: str, category: str, matched_categories: List[str]) -> str:
    normalized = normalize_for_matching(text)

    has_model_quality_issue = any(keyword in normalized for keyword in ["不准确", "不准", "答非所问", "回答错"])
    has_stability_issue = any(keyword in normalized for keyword in ["卡住", "卡", "慢", "无响应", "崩溃", "闪退"])
    has_copy_issue = "复制" in normalized
    if len(matched_categories) > 1 and has_model_quality_issue and has_stability_issue and has_copy_issue:
        return (
            "该反馈同时包含模型质量、性能稳定性和复制交互问题，建议先进入人工复核，拆分为答案准确性、"
            "页面卡顿复现、复制按钮链路三个问题分别定位。"
        )

    if "夜间模式" in normalized:
        return "围绕夜间模式补充显示设置能力，验证暗色主题、亮度对比度和低光环境阅读体验，并明确入口与切换策略。"

    if "知识库" in normalized and "审批流" in normalized:
        return "围绕企业办公场景验证团队知识库、审批流和协作权限需求，明确功能边界、数据接入范围和试点场景。"

    return SUGGESTION_BY_CATEGORY[category]


def detect_human_review_reasons(feedback: ClassifiedFeedback) -> List[str]:
    reasons: List[str] = []
    events = content_loss_events(feedback.review_text)
    if any(event.status == "reported" for event in events):
        reasons.append(CONTENT_LOSS_REASON)
    if any(event.status == "recovered" for event in events):
        reasons.append(RECOVERED_LOSS_REASON)
    is_positive_feedback = feedback.issue_category == "正向反馈/无明确问题"
    if compact_text_length(feedback.review_text) < 8 and not is_positive_feedback:
        reasons.append("文本过短")
    if feedback.issue_category == "不明确/其他" or feedback.confidence < 0.6:
        reasons.append("分类低置信度")
    if len(feedback.matched_categories) > 1:
        reasons.append("同时命中多个问题类型")
    if feedback.llm_rule_disagreement:
        reasons.append("LLM 与规则分类不一致")
    if feedback.issue_category == "内容安全与合规问题":
        reasons.append("内容安全与合规样本")
    if is_product_suggestion_too_generic(feedback.product_suggestion):
        reasons.append("product_suggestion 为空或过泛")
    if feedback.priority == "P0":
        reasons.append("P0 样本")
    return reasons


def classify_feedback_record(record: FeedbackRecord) -> ClassifiedFeedback:
    normalized = normalize_for_matching(record.review_text)
    scores, matched_keywords = score_categories(record.review_text)
    previous_category = pick_category(scores)
    events = content_loss_events(record.review_text)
    data_loss = any(event.status == "reported" for event in events)
    if data_loss:
        # Saving/finding a lost document is part of the data event, not a second
        # UI defect or a product-positioning issue merely because it says 'hope'.
        for category in ("交互体验问题", "用户预期与产品定位问题"):
            independent = []
            for word in matched_keywords.get(category, []):
                for left, _, clause in _clauses(normalized):
                    related = any(event.status == "reported" and event.start == left for event in events)
                    repair_wish = (
                        re.search(r"希望|请|能不能", clause)
                        and re.search(r"修复|恢复|找回", clause)
                        and not NON_DATA_OBJECT.search(clause)
                    )
                    if word in clause and not related and not repair_wish:
                        independent.append(word)
                        break
            if independent:
                matched_keywords[category] = independent
            else:
                matched_keywords.pop(category, None)
            scores[category] = len(independent)
        matched_keywords[DATA_CATEGORY] = [CONTENT_LOSS_REASON]
        scores[DATA_CATEGORY] = 1
    matched_categories = [category for category, score in scores.items() if score > 0]
    positive_hits = []
    if not matched_categories:
        positive_hits = detect_positive_feedback(record.review_text, record.rating)
    if positive_hits:
        category = "正向反馈/无明确问题"
        scores[category] = len(positive_hits)
        matched_categories = [category]
        matched_keywords[category] = positive_hits
    else:
        category = pick_category(scores)
    if data_loss:
        # Retain existing crash+loss primary labels and both category members.
        crash = any(
            contains_actionable_keyword(normalized, word, priority_check=True)
            for word in ("崩溃", "闪退", "crash", "crashes", "crashing", "crashed")
        )
        category = (
            previous_category if crash and previous_category in {"性能与稳定性问题", DATA_CATEGORY}
            else DATA_CATEGORY
        )
    priority = determine_priority(record.review_text, record.rating)
    confidence = calculate_confidence(scores, matched_categories)
    summary = summarize_text(record.review_text)
    return ClassifiedFeedback(
        id=record.id,
        record_key=record.id,
        source=record.source,
        app_name=record.app_name,
        review_text=record.review_text,
        rating=record.rating,
        issue_category=category,  # type: ignore[arg-type]
        rule_issue_category=category,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        confidence=confidence,
        rule_confidence=confidence,
        matched_categories=matched_categories,
        matched_keywords=matched_keywords,
        summary=summary,
        user_need=USER_NEED_BY_CATEGORY[category],
        product_suggestion=build_product_suggestion(record.review_text, category, matched_categories),
    )


def distribution(values: List[str]) -> Dict[str, int]:
    return dict(Counter(values))
