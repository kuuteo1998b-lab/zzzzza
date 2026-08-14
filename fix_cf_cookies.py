"""
🔧 FIX Cloudflare - Lưu cookie, tăng timeout, thêm delay
✅ Chạy: python fix_cf_cookies.py
"""

from pathlib import Path
import re

print("\n" + "="*60)
print("🔧 FIX CLOUDFLARE - COOKIE PERSISTENT")
print("="*60 + "\n")

# ==========================================
# 1. Update .env
# ==========================================
print("[1/3] Updating .env...")
env_file = Path(".env")
if env_file.exists():
    env_content = env_file.read_text(encoding='utf-8')
    
    # Sửa timeout
    env_content = re.sub(
        r'MANUAL_CF_TIMEOUT=\d+',
        'MANUAL_CF_TIMEOUT=900',
        env_content
    )
    
    # Sửa typing speed
    env_content = re.sub(
        r'HUMAN_LIKE_TYPING_SPEED=[\d.]+',
        'HUMAN_LIKE_TYPING_SPEED=0.08',
        env_content
    )
    
    # Sửa delay
    env_content = re.sub(
        r'RANDOM_DELAY_MIN=[\d.]+',
        'RANDOM_DELAY_MIN=0.2',
        env_content
    )
    
    env_content = re.sub(
        r'RANDOM_DELAY_MAX=[\d.]+',
        'RANDOM_DELAY_MAX=0.8',
        env_content
    )
    
    # Sửa browser slow mo
    env_content = re.sub(
        r'BROWSER_SLOW_MO=\d+',
        'BROWSER_SLOW_MO=150',
        env_content
    )
    
    env_file.write_text(env_content, encoding='utf-8')
    print("   ✅ .env updated")
else:
    print("   ⚠️ .env not found")

# ==========================================
# 2. Create CF cookie functions in main_script.py
# ==========================================
print("[2/3] Adding CF cookie functions to main_script.py...")

cookie_code = '''
# ==========================================
# ✅ CLOUDFLARE COOKIE PERSISTENCE (v7.6 FIX)
# ==========================================

async def save_cf_cookies(page, domain: str):
    """💾 Lưu Cloudflare cookie để dùng lại lần sau"""
    try:
        cookies = await page.context.cookies()
        cookie_file = Path(f"cf_cookies_{domain}.json")
        
        import json
        # Lọc chỉ CF cookies
        cf_cookies = [c for c in cookies if any(
            x in c['name'].lower() for x in ['cf', 'cfruid', 'turnstile']
        )]
        
        if cf_cookies:
            with open(cookie_file, 'w') as f:
                json.dump(cf_cookies, f)
            logger.info(f"💾 Lưu CF cookie: {domain} ({len(cf_cookies)} cookies)")
    except Exception as e:
        logger.debug(f"⚠️ Save cookie error: {e}")

async def load_cf_cookies(page, domain: str):
    """📂 Tải cookie CF cũ nếu có"""
    try:
        cookie_file = Path(f"cf_cookies_{domain}.json")
        
        if not cookie_file.exists():
            return False
        
        import json
        with open(cookie_file, 'r') as f:
            cookies = json.load(f)
        
        if cookies:
            await page.context.add_cookies(cookies)
            logger.info(f"📂 Tải CF cookie: {domain} ({len(cookies)} cookies)")
            return True
        return False
    except Exception as e:
        logger.debug(f"⚠️ Load cookie error: {e}")
        return False

async def clear_old_cf_cookies(domain: str):
    """🗑️ Xóa CF cookies quá cũ (>24h)"""
    try:
        import os, time
        cookie_file = Path(f"cf_cookies_{domain}.json")
        
        if cookie_file.exists():
            age = time.time() - cookie_file.stat().st_mtime
            if age > 86400:  # 24 hours
                cookie_file.unlink()
                logger.info(f"🗑️ Xóa CF cookie cũ: {domain}")
    except Exception:
        pass
'''

main_script = Path("main_script.py")
if main_script.exists():
    content = main_script.read_text(encoding='utf-8')
    
    # Thêm cookie code nếu chưa có
    if 'save_cf_cookies' not in content:
        # Tìm vị trí chèn (trước hàm verify_cf_and_retry_fixed)
        insert_pos = content.find('async def verify_cf_and_retry_fixed')
        if insert_pos > 0:
            content = content[:insert_pos] + cookie_code + '\n\n' + content[insert_pos:]
            main_script.write_text(content, encoding='utf-8')
            print("   ✅ CF cookie functions added")
        else:
            print("   ⚠️ Cannot find verify_cf_and_retry_fixed()")
    else:
        print("   ℹ️ CF cookie functions already exist")
else:
    print("   ⚠️ main_script.py not found")

# ==========================================
# 3. Create startup script
# ==========================================
print("[3/3] Creating run_bot_fixed.bat...")

bat_content = '''@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   BOT TELEGRAM - STARTUP (CF FIXED)
echo ========================================
echo.

REM Close Edge (giai phong lock file) - KHONG xoa profile / session
echo [1/3] Closing Edge...
taskkill /F /IM msedge.exe 2>nul
timeout /t 1 /nobreak >nul

REM ✅ FIX: KHONG con xoa browser_profiles\\bot_profile, session Telegram,
REM hay cache Edge ca nhan nua. Profile bot la profile CO DINH - giu
REM nguyen cookie/session/tab qua moi lan chay. Neu can reset thu cong,
REM tu xoa thu muc browser_profiles\\bot_profile.
echo [2/3] Giu nguyen browser profile + Telegram session...

REM Activate venv + Run bot
echo [3/3] Activating venv + Starting BOT...
cd /d C:\\bot_san_code
call venv\\Scripts\\activate

echo.
python main_script.py

pause
'''

bat_file = Path("run_bot_fixed.bat")
with open(bat_file, 'w', encoding='utf-8') as f:
    f.write(bat_content)

print("   ✅ run_bot_fixed.bat created")

print("\n" + "="*60)
print("✅ FIX COMPLETE!")
print("="*60)
print("\n📝 Changes made:")
print("   • Timeout CF: 600s → 900s (15 phút)")
print("   • Typing speed: 0.05 → 0.08")
print("   • Delay: 0.1-0.5s → 0.2-0.8s")
print("   • Browser slow: 100 → 150")
print("   • CF cookie persistence: ✅ Added")
print("\n🚀 Next step:")
print("   1. Double-click run_bot_fixed.bat")
print("   2. Bot will start automatically")
print("\n")