print("START", flush=True)
try:
    from scipy.stats import norm
    print("SCIPY OK", flush=True)
except Exception as e:
    print("SCIPY FAIL:", e, flush=True)

try:
    import ai_agent
    print("IMPORT OK", flush=True)
except SyntaxError as e:
    print(f"SYNTAX ERROR на строке {e.lineno}: {e.text}", flush=True)
    print(f"  {e.msg}", flush=True)
except Exception as e:
    print(f"IMPORT FAIL: {type(e).__name__}: {e}", flush=True)

print("END", flush=True)
