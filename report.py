"""Render a static glanceable page from balcony.db.

Everything is inlined - the PNGs are base64 in the HTML - so the page is a
single self-contained file that renders on any browser, however old.
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
LUX_HEADROOM = 1.4      # lux axis tops out this far above the week's peak
LUX_FALLBACK = 1000     # ...unless the week had no light at all
TITLE = "Plant: Desert Rose (adenium)"
SUBTITLE = "Tracking soil moisture, light, temperature and humidity readings."

SQL = """
SELECT feed, ts, value FROM readings
WHERE ts >= ?
  AND NOT (feed IN ('humidity','moisture-1') AND (value < 0 OR value > 100))
  AND NOT (feed = 'temp'  AND (value < 0 OR value > 60))
  AND NOT (feed = 'light' AND (value < 0 OR value > 150000))
"""

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def stamp(t):
    """A timezone-local wall-clock time: 13th Sept 0955 hrs.

    Absolute, not relative, so it stays true however long the page sits
    unregenerated on the display.
    """
    d = t.day
    suffix = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return "{}{} {} {:02d}{:02d} hrs".format(d, suffix, MONTHS[t.month - 1], t.hour, t.minute)


def load():
    """Returns (hourly frame, latest raw value per feed, newest timestamp)."""
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(SQL, conn, params=[int(time.time()) - DAYS * 86400])
    conn.close()
    if df.empty:
        return None, {}, None
    df["t"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
    newest = df["t"].max()
    # Tiles read the actual last reading, not the mean of a partial hour, so
    # watering the pot shows up immediately instead of being averaged away.
    last = df.sort_values("t").groupby("feed")["value"].last().to_dict()
    wide = df.pivot_table(index="t", columns="feed", values="value").resample("1h").mean()
    return wide, last, newest


def chart(series, color, ylabel, ymax, hline=None):
    fig, ax = plt.subplots(figsize=(9, 2.6), dpi=110)
    fig.patch.set_facecolor("#111")
    ax.set_facecolor("#111")
    # NaNs are left in on purpose: matplotlib breaks the line at a gap, so an
    # outage reads as a hole rather than a straight line across it.
    ax.plot(series.index, series.values, color=color, linewidth=2.4)
    if hline is not None:
        ax.axhline(hline, color="#c0392b", linestyle="--", linewidth=1.2)
    ax.set_ylim(0, ymax)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors="#777", labelsize=10)
    ax.grid(axis="y", color="#2a2a2a", linestyle="-", linewidth=0.6)
    ax.set_ylabel(ylabel, color="#777", fontsize=10)
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def panel(wide, col, color, ylabel, ymax, alt, hline=None):
    """One chart as an <img>, or nothing at all if that feed has no data."""
    if wide is None or col not in wide.columns or wide[col].dropna().empty:
        return ""
    png = chart(wide[col], color, ylabel, ymax, hline)
    return '<img src="data:image/png;base64,{}" alt="{}">'.format(png, alt)


def lux_ceiling(wide):
    if wide is None or "light" not in wide.columns:
        return LUX_FALLBACK
    peak = wide["light"].max()
    if pd.isna(peak) or peak <= 0:
        return LUX_FALLBACK
    return LUX_HEADROOM * peak


TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Balcony</title>
<style>
 body{{margin:0;background:#111;color:#eee;font-family:-apple-system,Helvetica,Arial,sans-serif;
      text-align:center;padding:24px 12px}}
 h1{{font-size:26px;font-weight:600;margin:0 0 4px}}
 .sub{{margin:0 0 20px;font-size:14px;color:#888;line-height:1.4}}
 .row{{display:flex;justify-content:center;gap:38px;margin:6px 0 16px;flex-wrap:wrap}}
 .n{{font-size:34px;font-weight:600}}
 .l{{font-size:13px;color:#888;letter-spacing:.05em}}
 img{{max-width:100%;height:auto;margin-top:8px}}
 .age{{margin-top:14px;font-size:14px;color:{acolor}}}
</style></head><body>
<h1>{title}</h1>
<p class="sub">{subtitle}</p>
<div class="row">{cells}</div>
{charts}
<div class="age">{age}</div>
</body></html>"""

def main():
    wide, last, newest = load()

    cells = ""
    for col, label, fmt in (("moisture-1", "MOISTURE", "{:.0f}%"),
                            ("temp", "TEMP", "{:.1f}C"),
                            ("humidity", "HUMIDITY", "{:.0f}%")):
        v = last.get(col)
        cells += '<div><div class="n">{}</div><div class="l">{}</div></div>'.format(
            "-" if v is None else fmt.format(v), label)

    charts = "\n".join(p for p in (
        panel(wide, "moisture-1", "#7ec8e3", "Moisture %", 100,
              "soil moisture, {} days".format(DAYS), hline=DRY_THRESHOLD),
        panel(wide, "light", "#e0c068", "Light", lux_ceiling(wide),
              "light, {} days".format(DAYS)),
    ) if p)

    if newest is None:
        age, acolor = "no readings in the last {} days".format(DAYS), "#c0392b"
    else:
        # Colour is a build-time judgement: how far behind the sensor was when
        # this page was written. The timestamp itself carries the real answer.
        mins = (pd.Timestamp.now(tz=TZ) - newest).total_seconds() / 60
        acolor = "#666" if mins < 90 else "#888" if mins < 1440 else "#c0392b"
        age = stamp(newest)

    html = TEMPLATE.format(title=TITLE, subtitle=SUBTITLE, cells=cells,
                           charts=charts, age=age, acolor=acolor)
    with open(OUT, "w") as f:
        f.write(html)
    print("wrote {} ({:.0f} KB), {}".format(OUT, len(html) / 1024, age))


if __name__ == "__main__":
    main()
