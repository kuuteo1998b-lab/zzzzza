"""
📋 CODE VALIDATOR - STRICT CODE FILTER
Ưu tiên code thật, chặn chữ quảng cáo, link, hashtag, username, domain và text chat.
Hỗ trợ gom nhiều kênh vào một nhóm lọc để dễ kiểm soát.
✅ MMOO: Hỗ trợ placeholder & tính toán
"""

import ast
import math
import operator
import re
from config import Config
from logger_setup import logger


# ✅ Safe math evaluator thay thế eval() cho placeholder MMOO
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def _safe_eval_math(expr: str):
    """Evaluate simple math expression safely (no eval())."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
        return _eval_node(tree.body)
    except Exception:
        raise ValueError(f"Invalid expression: {expr}")


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("Unsupported expression")


class CodeValidator:
    SITE_ROUTING_RULES = {
        "new88": ["NEW88", "N88", "NEW"],
        "mm88": ["MM88", "M88"],
        "llwin": ["LLWIN", "LLW", "LL"],
        "xx88": ["XX88", "XX"],
        "o8": ["O8"],
        "qq88": ["QQ88", "QQ"],
        "shbet": ["SHBET", "SH"],
        "jun88": ["JUN88", "JUN"],
        "789bet": ["789BET", "789B"],
        "hi88": ["HI88"],
        "f8bet": ["F8BET", "F8"],
        "mb66": ["MB66"],
    }

    COMMON_WORDS = [
        "CHUC", "MUNG", "HOM", "NAY", "NGAY", "THANG", "TANG", "LIXI", "NHAN", "THUONG",
        "DANG", "NHAP", "THAM", "GIA", "LINK", "GAME", "RUT", "NAP",
        "TIEN", "TAI", "KHOAN", "KHUYEN", "MAI", "DANGKY", "THANHCONG",
        "NHOM", "KENH", "ADMIN", "HOTRO", "CSKH", "ZALO", "TELE",
        "DANGNHAP", "MATKHAU", "LIENHE", "TRANGCHU", "NHACAI", "UYTIN",
        "BAOTRI", "NOHU", "BANCA", "THETHAO", "CASINO", "LODE", "XOSO",
        "KHONG", "DUOC", "HAY", "THOI", "GIAI", "TRI", "MUC", "VIP",
        "THEO", "DOI", "CHIA", "LIKE", "SHARE", "YOUTUBE",
        "MINIGAME", "O8THETHAO", "BONGDA", "TRUYCAP", "GIFTCODE", "EVENT",
        "FACEBOOK", "TELEGRAM", "TIKTOK", "WEBSITE", "OFFICIAL", "CHANNEL",
        "QUATANG", "BOT", "CHECK", "FREE", "ONLINE", "DAILY", "CLIP",
        "NHANH", "NHANHTAY", "ANH", "EM", "DUNG", "BO", "LO", "JACKPOT",
        "CANHBAO", "GIAMAO", "THONGBAO", "DANGNHAP", "BAOMAT", "KIEMTRA",
        "TAIDAY", "THONGTIN", "HOTLINE", "SUPPORT", "CHAT", "POST",
        "VIEW", "COMMENT", "PINNED", "SUBSCRIBE", "JOIN", "GROUP",
        "DANHSACH", "DIEUKIEN", "HUONGDAN", "KETQUA", "CHUCDANH", "PHAT",
        "XEMNGAY", "CLICK", "LOGIN", "PASSWORD", "TAIKHOAN", "KHUYENMAI",
        "TIENTHUONG", "SIEUTIENTHUONG", "SIEUPHAM",
        "DOTPHA", "GIAITHUONG", "GIAICUU", "CUOCTHUA",
        "NHANTHUONG", "MINHTHUONG", "PHANTHUONG",
        "NOHUBANCA", "BANCANO", "NOHUTAPDO",
        "SIEUKHUYEN", "SIEUNAP", "DOITHUONG",
        "REVIEWPHIM", "TINTUC", "TINTUCHANGAY",
        "NOHU47", "BANCA47",
        "VOUCHER", "BONUS", "GIFT", "REWARD", "PROMO", "PROMOTION",
        "WELCOME", "DEPOSIT", "WITHDRAW", "REGISTER", "SIGNUP",
    ]

    VIETNAMESE_TEXT_WORDS = [
        "khong", "dung", "nhanh", "tang", "code", "free", "clip", "vui",
        "dang", "nhap", "dangky", "truycap", "chinh", "thuc", "kenh",
        "thong", "bao", "canh", "gia", "mao", "kiem", "tra", "duong",
        "link", "facebook", "tiktok", "telegram", "zalo", "website",
        "hom", "nay", "anh", "em", "nhan", "qua", "thuong", "jackpot",
        "may", "man", "don", "cho", "chat", "bot", "cskh", "hotro",
        "lienhe", "taiday", "dangnhap", "matkhau", "taikhoan",
    ]

    FAKE_CODE_PATTERNS = [
        r"^(TEST|DEMO|EXAMPLE|FAKE|SAMPLE)",
        r"^(ABC|DEF|GHI|JKL|MNO|PQR|STU|VWX|YZ)$",
        r"^(123|456|789|000|111|222|333|444|555|666|777|888|999)$",
        r"^(AAAA|BBBB|CCCC|DDDD|EEEE|FFFF|GGGG|HHHH|IIII|JJJJ)$",
    ]

    SOFT_BLACKLIST = {"CODE", "GAME", "FREE", "VIP", "NAP", "RUT"}
    HARD_BLACKLIST = {
        "HTTP", "HTTPS", "WWW", "FACEBOOK", "TELEGRAM", "TIKTOK", "ZALO",
        "CHECK", "CLIP", "DAILY", "TRUYCAP", "BANCA", "NOHU", "ONLINE",
        "GIFTCODE", "MINIGAME", "THETHAO", "O8THETHAO", "BONGDA", "TROLL",
        "SUPPORT", "HOTLINE", "CSKH",
    }

    @staticmethod
    def clean_code(code):
        """
        Làm sạch code — xử lý các dạng đặc biệt:
        - XX88 BigWin: T*2*8*G*K*P*G*G → T28GKPGG (dấu * xen giữa từng ký tự)
        - o8: 9Q»KT»AZ >> 62_IR*9O → 9QKTAZ62IR9O
        - MM88: N*8W/T0#S → N8WT0S
        - MMOO/UY88: code bình thường có thể có dấu
        """
        if not code:
            return ""
        s = str(code).strip()

        # ✅ Dạng XX88 BigWin: mỗi ký tự cách nhau bởi * (ví dụ T*2*8*G*K*P*G*G)
        # Pattern: ký tự đơn xen kẽ dấu * liên tục
        import re as _re
        if _re.match(r'^[A-Za-z0-9](\*[A-Za-z0-9]){4,}$', s):
            return s.replace('*', '')

        # ✅ Dạng o8: có »» hoặc >> hoặc « làm separator giữa 2 phần code
        # Ví dụ: 9Q»KT»AZ >> 62_IR*9O → lấy toàn bộ, strip ký tự đặc biệt
        # ✅ MM88/o8: có * / # ~ + _ xen kẽ trong code
        return _re.sub(r"[^a-zA-Z0-9]", "", s).strip()

    @staticmethod
    def calculate_entropy(code):
        if not code:
            return 0.0

        char_freq = {}
        for char in code:
            char_freq[char] = char_freq.get(char, 0) + 1

        entropy = 0.0
        code_len = len(code)

        for freq in char_freq.values():
            p = freq / code_len
            if p > 0:
                entropy -= p * math.log2(p)

        return entropy

    @classmethod
    def get_filter_group(cls, target_url="", filter_group_name=None):
        groups = getattr(Config, "CODE_FILTER_GROUPS", {}) or {}

        if filter_group_name and filter_group_name in groups:
            return filter_group_name, groups[filter_group_name]

        target_lower = (target_url or "").lower()
        for group_name, group_config in groups.items():
            if group_name == "default":
                continue
            keywords = group_config.get("url_keywords", [])
            if any(str(keyword).lower() in target_lower for keyword in keywords):
                return group_name, group_config

        return "default", groups.get("default", {})

    @staticmethod
    def get_special_chars(group_config=None):
        group_config = group_config or {}
        return str(group_config.get("special_chars") or getattr(Config, "SPECIAL_CODE_CHARS_30", ""))

    @classmethod
    def count_special_chars(cls, raw_code, group_config=None):
        special_chars = set(cls.get_special_chars(group_config))
        return sum(1 for char in str(raw_code or "") if char in special_chars)

    @staticmethod
    def is_sequential_code(code):
        if not code:
            return True

        upper = code.upper()

        if len(set(upper)) <= 2 and len(upper) >= 6:
            return True

        if len(code) >= 4:
            pattern_1 = code[:1]
            if pattern_1 and pattern_1 * len(code) == code:
                return True

            pattern_2 = code[:2]
            if len(code) % 2 == 0 and pattern_2 * (len(code) // 2) == code:
                return True

            pattern_3 = code[:3]
            if len(code) % 3 == 0 and pattern_3 * (len(code) // 3) == code:
                return True

        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if re.fullmatch(r"[A-Z]+", upper) and len(upper) >= 4:
            if upper in alphabet or upper in alphabet[::-1]:
                return True

        digits = "0123456789"
        if code.isdigit() and len(code) >= 4:
            if code in digits or code in digits[::-1]:
                return True

        return False

    @staticmethod
    def looks_like_domain_or_link(code):
        upper = code.upper()

        if upper.startswith(("HTTP", "HTTPS", "WWW", "TME", "TELEGRAM", "FACEBOOK", "TIKTOK")):
            return True

        if upper.endswith(("COM", "NET", "ORG", "VN", "APP", "INFO")) and len(upper) <= 14:
            return True

        if any(fragment in upper for fragment in ("DOTCOM", "CHAMCOM", "COMVN", "NETVN")):
            return True

        return False

    @classmethod
    def detect_site_identity(cls, clean_code):
        clean_upper = clean_code.upper()

        for site_key, prefixes in cls.SITE_ROUTING_RULES.items():
            if any(clean_upper.startswith(prefix) for prefix in prefixes):
                return site_key

        return None

    @classmethod
    def has_code_shape(cls, code, group_config=None):
        if not code:
            return False

        group_config = group_config or {}
        length = len(code)

        min_len = int(group_config.get("min_clean_length", getattr(Config, "CODE_MIN_LENGTH", 6)) or 6)
        max_len = int(group_config.get("max_clean_length", getattr(Config, "CODE_MAX_LENGTH", 15)) or 15)

        if length < min_len:
            return False

        if length > max_len:
            return False

        if bool(group_config.get("require_uppercase", False)) and code != code.upper():
            return False

        has_lower = any(c.islower() for c in code)
        has_upper = any(c.isupper() for c in code)
        has_digit = any(c.isdigit() for c in code)
        has_letter = any(c.isalpha() for c in code)
        entropy = cls.calculate_entropy(code)
        min_entropy = float(group_config.get("min_entropy", 2.3))
        uppercase_min_entropy = float(group_config.get("uppercase_min_entropy", 2.9))
        allow_numeric = bool(group_config.get("allow_numeric", True))
        allow_random_mix = bool(group_config.get("allow_random_mix", True))

        if cls.detect_site_identity(code):
            return entropy >= min_entropy and not cls.is_sequential_code(code)

        if code.isdigit():
            return allow_numeric and 8 <= length <= 12 and entropy >= 2.6 and not cls.is_sequential_code(code)

        if not has_letter:
            return False

        if has_upper and has_lower:
            return allow_random_mix and entropy >= min_entropy

        if has_letter and has_digit:
            return entropy >= min_entropy

        if code.isupper() and length >= min_len and entropy >= uppercase_min_entropy:
            return True

        return False

    @classmethod
    def is_text_word(cls, code):
        lower = code.lower()
        upper = code.upper()

        if lower in cls.VIETNAMESE_TEXT_WORDS:
            return True

        if upper in cls.COMMON_WORDS:
            return True

        if code.islower() and not any(c.isdigit() for c in code):
            return True

        if code.isupper() and not any(c.isdigit() for c in code):
            if upper in cls.COMMON_WORDS:
                return True
            if len(code) <= 5:
                return True
            if len(code) <= 7 and cls.calculate_entropy(code) < 2.4:
                return True

        return False

    @classmethod
    def contains_blacklisted_fragment(cls, code, group_config=None):
        group_config = group_config or {}
        code_upper = code.upper()
        config_blacklist = {str(item).upper() for item in getattr(Config, "CODE_BLACKLIST", []) if str(item).strip()}
        group_soft_blacklist = {str(item).upper() for item in group_config.get("soft_blacklist", []) if str(item).strip()}

        soft_blacklist = cls.SOFT_BLACKLIST | group_soft_blacklist | (config_blacklist & cls.SOFT_BLACKLIST)
        hard_blacklist = cls.HARD_BLACKLIST | (config_blacklist - soft_blacklist)

        for word in hard_blacklist:
            if not word:
                continue
            if word == code_upper:
                return True
            if len(word) >= 5 and word in code_upper and len(code_upper) <= len(word) + 4:
                return True

        has_digit = any(c.isdigit() for c in code)
        has_lower = any(c.islower() for c in code)
        has_upper = any(c.isupper() for c in code)

        for word in soft_blacklist:
            if not word:
                continue
            if word == code_upper:
                return True
            if word in code_upper and len(code_upper) <= len(word) + 2 and not (has_digit or (has_lower and has_upper)):
                return True

        return False

    @classmethod
    def is_site_allowed_for_group(cls, site_identity, group_config):
        if not site_identity:
            return True

        allowed_sites = group_config.get("allowed_sites", []) if group_config else []
        if not allowed_sites:
            return True

        return site_identity in {str(site).lower() for site in allowed_sites}

    @classmethod
    def is_likely_fake(cls, code, group_config=None):
        code_upper = code.upper()
        group_config = group_config or {}

        if not cls.has_code_shape(code, group_config):
            return True

        for fake_pattern in cls.FAKE_CODE_PATTERNS:
            if re.match(fake_pattern, code_upper):
                return True

        if cls.is_sequential_code(code):
            return True

        if cls.looks_like_domain_or_link(code):
            return True

        if cls.is_text_word(code):
            return True

        if cls.contains_blacklisted_fragment(code, group_config):
            return True

        for word in cls.COMMON_WORDS:
            if word not in code_upper:
                continue
            has_digit_in_code = any(c.isdigit() for c in code_upper)
            # ✅ FIX: Từ quảng cáo DÀI (>=8 ký tự, ví dụ "THUONGTHANHTICH") gần như
            # KHÔNG BAO GIỜ xuất hiện tình cờ trong 1 code random thật — dù code có
            # lẫn số. Trước đây điều kiện `not has_digit_in_code` vô tình BỎ QUA
            # hẳn các trường hợp này chỉ vì code có số (ví dụ "THUONGTHANHTiCH388888K"
            # vẫn lọt qua vì có "388888"). Giờ tách riêng: từ càng dài càng chắc chắn
            # là rác quảng cáo, không cần đợi điều kiện "không có số" nữa.
            if len(word) >= 6:
                return True
            if len(code_upper) <= len(word) + 2 and not has_digit_in_code:
                return True

        code_upper_nospace = code.upper().replace(" ", "")
        for junk in cls.OCR_JUNK_KEYWORDS:
            if junk in code_upper_nospace:
                return True

        entropy = cls.calculate_entropy(code)
        min_entropy = float(group_config.get("min_entropy", 2.3))

        return entropy < min_entropy

    # ✅ MMOO PLACEHOLDER SUPPORT

    # Map chữ số tiếng Việt → số (dùng trong placeholder)
    _VIET_DIGIT_MAP = {
        "không": "0", "khong": "0",
        "một": "1", "mot": "1",
        "hai": "2",
        "ba": "3",
        "bốn": "4", "bon": "4",
        "năm": "5", "nam": "5",
        "sáu": "6", "sau": "6",
        "bảy": "7", "bay": "7",
        "tám": "8", "tam": "8",
        "chín": "9", "chin": "9",
    }

    @classmethod
    def _resolve_viet_number(cls, text: str) -> str:
        """
        Chuyển "số chín" / "số 5" / "số năm" → "9" / "5" / "5".
        Trả về chuỗi số nếu nhận ra, ngược lại trả về text gốc.
        """
        text_lower = text.strip().lower()

        # Dạng "số N" (có chữ "số" hoặc "so" đứng trước)
        m = re.match(r'^s[oố]\s*(\d+)$', text_lower)
        if m:
            return m.group(1)

        # Dạng "số <chữ_số>" — e.g. "số chín", "số năm"
        m = re.match(r'^s[oố]\s+(.+)$', text_lower)
        if m:
            word = m.group(1).strip()
            if word in cls._VIET_DIGIT_MAP:
                return cls._VIET_DIGIT_MAP[word]

        # Dạng chỉ chữ số thuần — e.g. "chín", "năm"
        if text_lower in cls._VIET_DIGIT_MAP:
            return cls._VIET_DIGIT_MAP[text_lower]

        return text  # Không nhận ra → giữ nguyên

    @classmethod
    def _expand_placeholder_code(cls, code: str) -> list:
        """
        ✅ Mở rộng code có placeholder thành 1 code thực.
        Xử lý đủ 4 dạng MMOO thực tế:

        Dạng 1 — ngoặc nhọn + toán học:
          VqbEmDM<8+1>NB3KfZVNhB   → VqbEmDM9NB3KfZVNhB
          VbVD<3+6>a2D6UaxvVpwQ4R  → VbVD9a2D6UaxvVpwQ4R

        Dạng 2 — ngoặc nhọn + tiếng Việt:
          SXRglFuErLL<số 5>u3Lzzh  → SXRglFuErLL5u3Lzzh

        Dạng 3 — dấu nháy kép + tiếng Việt (không ngoặc nhọn):
          zQAWwNTeBpQbnNh"số chín"hdY → zQAWwNTeBpQbnNh9hdY

        Dạng 4 — code thuần, không có placeholder:
          tdmYKxmcUXsHueZpNTj       → [tdmYKxmcUXsHueZpNTj]
        """
        result = code

        # ── Bước 1: Thay thế dạng ngoặc nhọn <...> ─────────────────────────
        angle_pattern = r'<([^>]+)>'
        for match in re.finditer(angle_pattern, result):
            placeholder_text = match.group(1).strip()

            # Thử tiếng Việt trước
            resolved = cls._resolve_viet_number(placeholder_text)
            if resolved != placeholder_text and resolved.isdigit():
                result = result.replace(match.group(0), resolved, 1)
                continue

            # Thử biểu thức toán học thuần
            if re.match(r'^[\d+\-*/%\s()]+$', placeholder_text):
                try:
                    computed = str(int(_safe_eval_math(placeholder_text)))
                    result = result.replace(match.group(0), computed, 1)
                except Exception:
                    pass  # Giữ nguyên nếu lỗi

        # ── Bước 2: Thay thế dạng nháy kép "..." ───────────────────────────
        quote_pattern = r'"([^"]+)"'
        for match in re.finditer(quote_pattern, result):
            inner = match.group(1).strip()
            resolved = cls._resolve_viet_number(inner)
            if resolved != inner and resolved.isdigit():
                result = result.replace(match.group(0), resolved, 1)

        return [result]

    # ✅ MMOO PLACEHOLDER KEYWORDS
    OCR_JUNK_KEYWORDS = [
        "TIENTHUONG", "NOHUBAN", "BANCANO", "SIEUTHUO",
        "DOTPHA", "GIAICUU", "CUOCTHUA", "REVIEWPHIM",
        "TINTUCMO", "NOHUTAP", "KHOGIF",
        "IENTHU", "IEUTHU", "AKTIEN", "SIKTIEN",
    ]

    @classmethod
    def validate_code(cls, code, target_url="", filter_group_name=None, source="normal"):
        """✅ Validate code - CÓ HỖ TRỢ PLACEHOLDER CHO MMOO."""
        raw_code = str(code or "").strip()

        # ✅ BƯỚC 1: Lấy group config (1 lần duy nhất)
        group_name, group_config = cls.get_filter_group(target_url, filter_group_name)
        enable_placeholder = bool(group_config.get("enable_placeholder_mode", False))

        # ✅ BƯỚC 2: Mở rộng placeholder nếu được bật
        # Trigger khi có <...> hoặc "..." (dạng tiếng Việt nháy kép)
        has_angle = '<' in raw_code and '>' in raw_code
        has_quote_viet = bool(re.search(r'"s[oố]\s*\w+"', raw_code))

        if enable_placeholder and (has_angle or has_quote_viet):
            logger.info(f"🔧 [MMOO] Placeholder detected: {raw_code}")
            expanded_codes = cls._expand_placeholder_code(raw_code)
            expanded = expanded_codes[0] if expanded_codes else raw_code

            if expanded != raw_code:
                logger.info(f"✅ [MMOO] Expanded: {raw_code} → {expanded}")
                raw_code = expanded

        # ✅ BƯỚC 3: Validate bình thường
        clean_code = cls.clean_code(raw_code)
        special_count = cls.count_special_chars(raw_code, group_config)

        result = {
            "valid": False,
            "confidence": 0.0,
            "reason": "",
            "is_fake": False,
            "entropy": 0.0,
            "recommendation": "SKIP",
            "clean_code": clean_code,
            "raw_code": raw_code,
            "filter_group": group_name,
            "special_count": special_count,
            "source": source,
        }

        # ✅ FIX: OCR đọc ảnh chất lượng kém hay ra text rác lẫn chữ tiếng Việt/watermark
        # (ví dụ "20200NGAY03774" từ dòng ngày-tháng trên ảnh). Entropy/độ dài đơn thuần
        # không đủ để loại — nên với nguồn OCR, kiểm tra thêm: nếu chuỗi chứa nguyên vẹn
        # 1 từ trong COMMON_WORDS (>=4 ký tự) thì gần như chắc chắn là rác OCR, không phải code thật
        # (code thật do site tự sinh ngẫu nhiên, cực hiếm trùng khớp 1 từ có nghĩa dài như vậy).
        # ✅ FIX: Trước đây chỉ check nguồn "image_ocr" — nguồn "marker" (lấy từ
        # text thường, không phải OCR ảnh) cũng có thể dính chữ rác/quảng cáo
        # tiếng Việt hoặc tiếng Anh (ví dụ "Voucher") lọt qua vì thiếu bước lọc
        # này. Mở rộng áp dụng cho cả "marker" để chặn sớm hơn.
        if source in ("image_ocr", "marker"):
            clean_upper_ocr = clean_code.upper()
            for word in cls.COMMON_WORDS:
                if len(word) >= 4 and word in clean_upper_ocr:
                    result["is_fake"] = True
                    tag = "OCR" if source == "image_ocr" else "MARKER"
                    result["reason"] = f"🚫 [{tag}] Nghi rác — chứa từ '{word}': {clean_code}"
                    return result

        min_len = int(group_config.get("min_clean_length", getattr(Config, "CODE_MIN_LENGTH", 6)) or 6)
        max_len = int(group_config.get("max_clean_length", getattr(Config, "CODE_MAX_LENGTH", 15)) or 15)

        if len(clean_code) < min_len or len(clean_code) > max_len:
            result["reason"] = f"❌ Độ dài không hợp lệ: {len(clean_code)}"
            return result

        min_special_chars = 0
        if source not in ("spoiler", "marker"):
            min_special_chars = int(group_config.get("min_special_chars", 0) or 0)

        if min_special_chars > 0 and special_count < min_special_chars:
            result["reason"] = f"🚫 Không đủ dấu đặc biệt: {special_count}/{min_special_chars} ({group_name})"
            return result

        if bool(group_config.get("require_uppercase", False)) and clean_code != clean_code.upper():
            result["reason"] = f"🚫 Mã không viết hoa đúng chuẩn ({group_name})"
            return result

        target_lower = target_url.lower() if target_url else ""
        site_identity = cls.detect_site_identity(clean_code)
        clean_upper = clean_code.upper()

        if group_name == "new88":
            if clean_upper.startswith(("NEW88", "N88", "NEW")):
                result["reason"] = f"🚫 NEW88 prefix giống chữ quảng cáo, không nhận là code ({group_name})"
                return result

            promo_fragments = [
                "TROLAI", "TRLAI", "XTL", "NOHU", "BANCA", "MIENPHI",
                "KHUYENMAI", "PHATCODE", "GIFTCODE", "EVENT", "FREECODE",
            ]

            if any(fragment in clean_upper for fragment in promo_fragments):
                result["reason"] = f"🚫 Dính chữ quảng cáo NEW88: {clean_upper}"
                return result

        if site_identity and not cls.is_site_allowed_for_group(site_identity, group_config):
            result["reason"] = f"🛡️ Code [{site_identity.upper()}] không thuộc nhóm lọc [{group_name}]"
            return result

        if site_identity and target_lower and site_identity not in target_lower:
            result["reason"] = (
                f"🛡️ CHỐNG NHẬP SAI: Code [{site_identity.upper()}] "
                f"không thuộc trang [{target_url}]"
            )
            return result

        entropy = cls.calculate_entropy(clean_code)
        result["entropy"] = round(entropy, 2)

        if cls.is_likely_fake(clean_code, group_config):
            result["is_fake"] = True
            result["reason"] = f"🚫 Nhận diện là chữ quảng cáo / link / text rác ({group_name})"
            return result

        min_entropy = float(group_config.get("min_entropy", 2.3))
        has_lower = any(c.islower() for c in clean_code)
        has_upper = any(c.isupper() for c in clean_code)
        has_digit = any(c.isdigit() for c in clean_code)

        if site_identity:
            result["valid"] = True
            result["confidence"] = 1.0
            result["reason"] = f"🌟 Code có định danh {site_identity.upper()} hợp lệ ({group_name})"
            result["recommendation"] = "SUBMIT"
            return result

        if clean_code.isdigit() and bool(group_config.get("allow_numeric", True)) and entropy >= 2.6:
            result["valid"] = True
            result["confidence"] = 0.9
            result["reason"] = f"✅ Code hợp lệ dạng toàn số ({group_name})"
            result["recommendation"] = "SUBMIT"
            return result

        if has_lower and has_upper and entropy >= min_entropy:
            result["valid"] = True
            result["confidence"] = 0.95
            result["reason"] = f"✅ Code hợp lệ dạng mix chữ hoa/thường ({group_name})"
            result["recommendation"] = "SUBMIT"
            return result

        if has_digit and entropy >= min_entropy:
            result["valid"] = True
            result["confidence"] = 0.92
            result["reason"] = f"✅ Code hợp lệ dạng có số ({group_name})"
            result["recommendation"] = "SUBMIT"
            return result

        if entropy >= float(group_config.get("uppercase_min_entropy", 2.9)):
            result["valid"] = True
            result["confidence"] = 0.85
            result["reason"] = f"✅ Code hợp lệ độ ngẫu nhiên cao ({group_name})"
            result["recommendation"] = "SUBMIT"
            return result

        result["reason"] = f"🚫 Không đủ đặc điểm code thật ({group_name})"
        return result