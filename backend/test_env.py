from app.config import settings
k = settings.RAPIDAPI_KEY
print(f"Loaded KEY: length={len(k)}, starts='{k[:3]}', ends='{k[-3:]}', repr={repr(k)[:15]}...")
