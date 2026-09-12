"""Render a static glanceable page from balcony.db.

Everything is inlined - the PNG is base64 in the HTML - so the page is a single
self-contained file that renders on any browser, however old.
"""
import base64, io, sqlite3, time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DB = "balcony.db"
OUT = "index.html"
TZ = "Asia/Bangkok"
DAYS = 7
DRY_THRESHOLD = 30

SQL = """
SELECT feed, ts, value FROM readings
WHERE ts >= ?
  AND NOT (feed IN ('humidity','moisture-1') AND (value < 0 OR value > 100))
  AND NOT (feed = 'temp'  AND (value < 0 OR value > 60))
  AND NOT (feed = 'light' AND (value < 0 OR value > 150000))
"""


def load():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(SQL, conn, params=[int(time.time()) - DAYS * 86400])
    conn.close()
    df["t"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
    return df.pivot_table(index="t", columns="feed", values="value").resample("1h").mean()


def chart(wide):
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=110)
    fig.patch.set_facecolor("#111")
    ax.set_facecolor("#111")
    ax.plot(wide.index, wide["moisture-1"], color="#7ec8e3", linewidth=2.4)
    ax.axhline(DRY_THRESHOLD, color="#c0392b", linestyle="--", linewidth=1.2)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors="#777", labelsize=10)
    ax.grid(axis="y", color="#2a2a2a", linestyle="-", linewidth=0.6)
    ax.set_ylabel("moisture %", color="#777", fontsize=10)
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def latest(wide, col):
    s = wide[col].dropna() if col in wide.columns else pd.Series(dtype=float)
    return None if s.empty else s.iloc[-1]


TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Balcony</title>
<style>
 body{{margin:0;background:#111;color:#eee;font-family:-apple-system,Helvetica,Arial,sans-serif;
      text-align:center;padding:24px 12px}}
 .verdict{{font-size:44px;font-weight:600;margin:4px 0 2px;color:{vcolor}}}
 .row{{display:flex;justify-content:center;gap:38px;margin:18px 0 10px;flex-wrap:wrap}}
 .n{{font-size:34px;font-weight:600}}
 .l{{font-size:13px;color:#888;letter-spacing:.05em}}
 img{{max-width:100%;height:auto;margin-top:8px}}
 .age{{margin-top:14px;font-size:14px;color:{acolor}}}
</style></head><body>
<div class="verdict">{verdict}</div>
<div class="row">{cells}</div>
<img src="data:image/png;base64,{png}" alt="soil moisture, 7 days">
<div class="age">{age}</div>
</body></html>"""


def main():
    wide = load()
    m = latest(wide, "moisture-1")

    if m is None:
        verdict, vcolor = "No data", "#c0392b"
    elif m <= DRY_THRESHOLD:
        verdict, vcolor = "Needs water", "#e08a3c"
    else:
        verdict, vcolor = "Fine", "#6bbf59"

    cells = ""
    for col, label, fmt in (("moisture-1", "MOISTURE", "{:.0f}%"),
                            ("temp", "TEMP", "{:.1f}C"),
                            ("humidity", "HUMIDITY", "{:.0f}%")):
        v = latest(wide, col)
        cells += '<div><div class="n">{}</div><div class="l">{}</div></div>'.format(
            "-" if v is None else fmt.format(v), label)

    newest = wide.dropna(how="all").index.max()
    mins = (pd.Timestamp.now(tz=TZ) - newest).total_seconds() / 60
    if mins < 90:
        age, acolor = "updated {:.0f} min ago".format(mins), "#666"
    elif mins < 1440:
        age, acolor = "updated {:.0f} hours ago".format(mins / 60), "#888"
    else:
        age, acolor = "STALE - {:.0f} days old".format(mins / 1440), "#c0392b"

    html = TEMPLATE.format(verdict=verdict, vcolor=vcolor, cells=cells,
                           png=chart(wide), age=age, acolor=acolor)
    with open(OUT, "w") as f:
        f.write(html)
    print("wrote {} ({:.0f} KB), {}".format(OUT, len(html) / 1024, age))


if __name__ == "__main__":
    main()
