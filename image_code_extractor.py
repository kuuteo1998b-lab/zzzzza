"""
🖼️ IMAGE CODE EXTRACTOR - OCR MODULE (LIGHT & FAST)
Trích xuất mã code từ hình ảnh - Cấu hình nhẹ, nhanh, chuẩn
- OCR trực tiếp, không tiền xử lý phức tạp
- Tối ưu cho speed, không cần GPU
- Hỗ trợ đa ngôn ngữ
"""

import os
import pytesseract
from pathlib import Path
from logger_setup import logger


def configure_tesseract() -> None:
    """
    Đọc TESSERACT_PATH từ Config (hoặc env trực tiếp) và gán vào
    pytesseract.pytesseract.tesseract_cmd.
    Bắt buộc trên Windows nếu Tesseract không nằm trong PATH.
    """
    # Ưu tiên Config nếu đã import được; fallback sang os.getenv
    try:
        from config import Config
        path = getattr(Config, "TESSERACT_PATH", "") or ""
    except Exception:
        path = ""
    if not path:
        path = os.getenv("TESSERACT_PATH", "")
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
        logger.debug(f"🔧 Tesseract cmd set → {path}")


# Áp dụng ngay khi module được import
configure_tesseract()


class ImageCodeExtractor:
    """Trích xuất code từ hình ảnh - Phiên bản nhẹ & nhanh"""
    
    def __init__(self):
        """Khởi tạo OCR extractor"""
        self.supported_formats = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp']
        self._check_tesseract()
        logger.info("✅ ImageCodeExtractor ready (lightweight version)")
    
    def _check_tesseract(self):
        """Kiểm tra Tesseract đã cài hay chưa"""
        try:
            pytesseract.get_tesseract_version()
            logger.debug("✅ Tesseract OCR available")
        except Exception as e:
            logger.error(
                f"❌ Tesseract not installed! ({e})\n"
                f"   Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                f"   Linux: sudo apt-get install tesseract-ocr\n"
                f"   macOS: brew install tesseract"
            )
            raise
    
    def extract_code_from_image(self, image_path: str, lang: str = "eng") -> str:
        """
        Trích xuất code từ ảnh — có tiền xử lý để tăng độ chính xác.

        Args:
            image_path: Đường dẫn file ảnh
            lang: Ngôn ngữ OCR ('eng', 'vie', v.v.)

        Returns:
            Text đã OCR (chuỗi rỗng nếu không có)
        """
        try:
            image_path = Path(image_path)

            if not image_path.exists():
                logger.warning(f"⚠️ File not found: {image_path}")
                return ""

            if image_path.suffix.lower() not in self.supported_formats:
                logger.warning(f"⚠️ Format not supported: {image_path.suffix}")
                return ""

            logger.info(f"📸 OCR image: {image_path.name}")

            # ── Thử với tiền xử lý ảnh (Pillow) ──────────────────────────────
            try:
                from PIL import Image, ImageFilter, ImageEnhance, ImageOps
                base_img = Image.open(str(image_path)).convert("L")  # grayscale
                # ✅ FIX: Tesseract đọc ảnh nhỏ rất kém — ảnh Telegram hay bị nén/thu nhỏ.
                # Phóng to lên nếu ảnh nhỏ hơn ngưỡng, tăng đáng kể độ chính xác OCR.
                min_width = 1000
                if base_img.width < min_width:
                    scale = min_width / base_img.width
                    new_size = (min_width, int(base_img.height * scale))
                    base_img = base_img.resize(new_size, Image.LANCZOS)

                # ✅ FIX: ảnh khuyến mãi thường chữ SÁNG trên nền TỐI/nhiều màu
                # (banner gradient) — kiểu ảnh này contrast/sharpen đơn thuần vẫn
                # đọc rất kém (ra chữ rác như "HURIBANICA"). Giờ thử NHIỀU biến
                # thể ảnh khác nhau, biến thể nào cho kết quả dài nhất/hợp lệ nhất
                # thì dùng — thay vì chỉ thử đúng 1 kiểu xử lý như trước.
                variants = []

                # Biến thể 1: contrast + sharpen (như cũ)
                v1 = ImageEnhance.Contrast(base_img).enhance(2.0)
                v1 = v1.filter(ImageFilter.SHARPEN)
                variants.append(("contrast", v1))

                # Biến thể 2: auto-contrast (tự cân bằng theo từng ảnh thay vì
                # hệ số cố định 2.0 — tốt hơn với ảnh có độ sáng/tối khác nhau)
                v2 = ImageOps.autocontrast(base_img, cutoff=2)
                variants.append(("autocontrast", v2))

                # Biến thể 3: đảo màu (invert) — xử lý đúng trường hợp chữ
                # sáng trên nền tối, vì Tesseract vốn tối ưu cho chữ tối trên
                # nền sáng (giấy trắng)
                v3 = ImageOps.invert(ImageOps.autocontrast(base_img, cutoff=2))
                variants.append(("inverted", v3))

                # Biến thể 4: nhị phân hóa (đen/trắng tuyệt đối) — loại bỏ hẳn
                # nhiễu màu nền, chỉ giữ lại hình dạng chữ
                threshold = 140
                v4 = base_img.point(lambda p: 255 if p > threshold else 0)
                variants.append(("binarized", v4))

                best_cleaned = ""
                best_variant_name = ""
                for variant_name, img in variants:
                    custom_config = r"--oem 3 --psm 6"
                    text = pytesseract.image_to_string(img, lang=lang, config=custom_config)
                    cleaned = self._clean_text(text)
                    if not cleaned and lang == "eng":
                        custom_config2 = r"--oem 3 --psm 11"
                        text2 = pytesseract.image_to_string(img, lang=lang, config=custom_config2)
                        cleaned = self._clean_text(text2)
                    # Chọn biến thể cho ra text DÀI HƠN (thường đồng nghĩa đọc
                    # được nhiều chữ hơn = ít bỏ sót hơn). Không phải luôn đúng
                    # 100% nhưng là tín hiệu thực dụng, rẻ để tính.
                    if len(cleaned) > len(best_cleaned):
                        best_cleaned = cleaned
                        best_variant_name = variant_name

                cleaned = best_cleaned
                if best_variant_name:
                    logger.debug(f"🎨 [OCR] Biến thể tốt nhất: {best_variant_name}")

            except ImportError:
                # Pillow không có → OCR thẳng
                custom_config = r"--oem 3 --psm 6"
                text = pytesseract.image_to_string(str(image_path), lang=lang, config=custom_config)
                cleaned = self._clean_text(text)

            if cleaned:
                logger.info(f"✅ Extracted: {len(cleaned)} chars")
            else:
                logger.warning("⚠️ No text detected in image")

            return cleaned

        except Exception as e:
            logger.error(f"❌ OCR error: {e}")
            return ""
    
    def _clean_text(self, text: str) -> str:
        """Làm sạch text: xóa dòng trống, khoảng trắng thừa"""
        if not text:
            return ""
        
        # Xóa dòng trống
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Nối lại
        return '\n'.join(lines)

# Global instance
_image_extractor = None

def init_image_extractor() -> ImageCodeExtractor:
    """Khởi tạo image extractor"""
    global _image_extractor
    if _image_extractor is None:
        try:
            _image_extractor = ImageCodeExtractor()
        except Exception as e:
            logger.error(f"❌ Cannot init image extractor: {e}")
            return None
    return _image_extractor

def get_image_extractor() -> ImageCodeExtractor:
    """Lấy image extractor instance"""
    global _image_extractor
    if _image_extractor is None:
        _image_extractor = init_image_extractor()
    return _image_extractor