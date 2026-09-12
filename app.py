import sqlite3, time

import altair as alt
import pandas as pd
import streamlit as st

DB = "balcony.db"
TZ = "Asia/Bangkok"
START = "2026-09-07"          # first clean day; Sep 5-6 was the BME280 install
DRY_THRESHOLD = 30            # PLACEHOLDER - set this from your own watering experience

LABELS = {
    "moisture-1": "Soil moisture (%)",
    "temp": "Temperature (C)",
    "humidity": "Humidity (%)",
    "light": "Light (lux)",
}

INK   = "#3c3c3c"             # primary series: the thing being asked about
MUTED = "#b4b4b4"             # context series: present, not competing
ALERT = "#c0392b"
COOL  = "#4c78a8"

SQL = """
SELECT feed, ts, value FROM readings
WHERE ts >= ?
  AND NOT (feed IN ('humidity','moisture-1') AND (value < 0 OR value > 100))
  AND NOT (feed = 'temp'  AND (value < 0 OR value > 60))
  AND NOT (feed = 'light' AND (value < 0 OR value > 150000))
"""

st.set_page_config(page_title="Balcony", layout="wide")


@st.cache_data(ttl=300)
def load(days):
    cutoff = max(int(time.time()) - days * 86400,
                 int(pd.Timestamp(START, tz=TZ).timestamp()))
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(SQL, conn, params=[cutoff])
    conn.close()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
    return df.pivot_table(index="t", columns="feed", values="value")


def _tooltip(cols):
    tips = [alt.Tooltip("t:T", title="", format="%a %d %b, %H:%M")]
    tips += [alt.Tooltip(c + ":Q", title=LABELS.get(c, c), format=".1f") for c in cols]
    return tips


def _finish(chart):
    return (chart.properties(height=260)
                 .configure_view(stroke=None)
                 .configure_axis(domain=False, ticks=False, grid=False,
                                 labelColor="#888", titleColor="#888",
                                 labelFontSize=11, titleFontSize=11, titlePadding=8)
                 .configure_axisY(grid=True, gridColor="#eee", gridDash=[2, 2])
                 .configure_legend(orient="top", direction="horizontal", title=None,
                                   labelColor=INK, labelFontSize=12, offset=4))


def single(wide, col, color, rule_at=None):
    d = wide.reset_index()[["t", col]].dropna()
    hover = alt.selection_point(nearest=True, on="pointerover",
                                fields=["t"], empty=False, clear="pointerout")
    base = alt.Chart(d).encode(x=alt.X("t:T", title=None))
    line = base.mark_line(color=color, strokeWidth=1.8).encode(
        y=alt.Y(col + ":Q", title=LABELS.get(col, col), scale=alt.Scale(zero=False)))
    dot = line.mark_point(color=color, size=45, filled=True).transform_filter(hover)
    grab = base.mark_rule(color="#bbb").encode(
        opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=_tooltip([col])).add_params(hover)
    layers = [line, dot, grab]
    if rule_at is not None:
        ref = (alt.Chart(pd.DataFrame({"y": [rule_at]}))
                  .mark_rule(color=ALERT, strokeDash=[4, 4], strokeWidth=1)
                  .encode(y="y:Q"))
        layers.insert(0, ref)
    return _finish(alt.layer(*layers))


def dual(wide, left, right, left_color, right_color):
    d = wide.reset_index()[["t", left, right]].dropna()
    hover = alt.selection_point(nearest=True, on="pointerover",
                                fields=["t"], empty=False, clear="pointerout")
    base = alt.Chart(d).encode(x=alt.X("t:T", title=None))
    scale = alt.Scale(domain=[LABELS[left], LABELS[right]],
                      range=[left_color, right_color])

    def side(col, color, label):
        return (base.transform_calculate(series="'" + label + "'")
                    .mark_line(strokeWidth=1.8)
                    .encode(y=alt.Y(col + ":Q", title=label, scale=alt.Scale(zero=False),
                                    axis=alt.Axis(titleColor=color)),
                            color=alt.Color("series:N", scale=scale, title=None)))

    grab = base.mark_rule(color="#bbb").encode(
        opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=_tooltip([left, right])).add_params(hover)
    return _finish(alt.layer(side(left, left_color, LABELS[left]),
                             side(right, right_color, LABELS[right]),
                             grab).resolve_scale(y="independent"))


def trend(series, unit, noun):
    """One-line takeaway computed from the data, not a static description."""
    s = series.dropna()
    if len(s) < 2:
        return ""
    delta = s.iloc[-1] - s.iloc[0]
    if abs(delta) < 0.5:
        return "{} has held steady near {:.1f}{}".format(noun, s.mean(), unit)
    word = "risen" if delta > 0 else "fallen"
    return "{} has {} {:.1f}{} over this window, now {:.1f}{}".format(
        noun, word, abs(delta), unit, s.iloc[-1], unit)


days = st.sidebar.slider("Days", 1, 30, 7)
freq = st.sidebar.select_slider("Smoothing", ["10min", "30min", "1h", "3h"], value="1h")
st.sidebar.caption("Data starts " + START)

raw = load(days)
if raw.empty:
    st.warning("No readings in this window. Has puller.py run?")
    st.stop()
wide = raw.resample(freq).mean()

st.subheader("Desert Rose, balcony")

cols = st.columns(len(wide.columns))
for col, feed in zip(cols, wide.columns):
    s = wide[feed].dropna()
    if s.empty:
        col.metric(LABELS.get(feed, feed), "-")
    else:
        col.metric(LABELS.get(feed, feed), "{:.1f}".format(s.iloc[-1]),
                   "{:+.1f}".format(s.iloc[-1] - s.iloc[0]),
                   delta_color="off" if feed == "light" else "normal")

if "moisture-1" in wide.columns:
    st.markdown("#### " + trend(wide["moisture-1"], "%", "Soil moisture"))
    st.caption("Dashed line marks the {}% watering threshold".format(DRY_THRESHOLD))
    st.altair_chart(single(wide, "moisture-1", INK, rule_at=DRY_THRESHOLD),
                    use_container_width=True)

if {"temp", "humidity"} <= set(wide.columns):
    st.markdown("#### Humidity falls as the balcony heats up")
    st.altair_chart(dual(wide, "temp", "humidity", ALERT, COOL), use_container_width=True)

if "light" in wide.columns:
    peaks = wide["light"].resample("1D").max().dropna()
    st.markdown("#### Daily light peaks near {:.0f} lux under the dome".format(peaks.median())
                if len(peaks) else "#### Light")
    st.altair_chart(single(wide, "light", MUTED), use_container_width=True)

with st.expander("Coverage and raw data"):
    st.caption("Readings stored per day (about 142 is a full day)")
    st.dataframe(raw.resample("1D").count().rename(columns=lambda c: LABELS.get(c, c)))
    st.dataframe(wide.tail(200).round(1))
