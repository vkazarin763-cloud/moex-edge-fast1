print("START", flush=True)
try:
    from scipy.stats import norm
    print("SCIPY OK", flush=True)
except Exception as e:
    print("SCIPY FAIL:", e, flush=True)
print("END", flush=True)
