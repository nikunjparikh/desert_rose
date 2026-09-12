import time, network, urequests, gc
from machine import ADC, Pin, SoftI2C, WDT
import secrets
import bme280
# ---- config ----
DRY, WET = 4093, 2143          # calibration anchors
INTERVAL = 600                  # seconds between readings
BME_ADDR = 118                  # from i2c.scan()
# ---- hardware ----
adc = ADC(Pin(34))
adc.atten(ADC.ATTN_11DB)
i2c = SoftI2C(scl=Pin(22), sda=Pin(21), freq=50000)
led = Pin(2, Pin.OUT)
# ---- watchdog ----
# If the board ever truly locks up, this restarts it on its own.
# It has to be "fed" regularly; if we go quiet too long, it assumes
# we're frozen and reboots. 60s is comfortably longer than a normal
# reading + send, but short enough to recover from a real hang quickly.
wdt = WDT(timeout=60000)        # milliseconds
def sleep_fed(seconds):
    # A normal sleep, but we tap the watchdog once a second so it
    # doesn't reboot us during the ordinary 10-minute wait.
    for _ in range(seconds):
        wdt.feed()
        time.sleep(1)
# ---- bme280 ----
# Created once at startup, after the watchdog so a failure here can't
# boot-loop us. If the sensor is missing we carry on without it.
bme = None
try:
    b = bme280.BME280(i2c=i2c, address=BME_ADDR)
    b.read_compensated_data()   # first sample after power-up is junk; discard it
    bme = b
    print("bme280 ready")
except Exception as e:
    print("bme280 init failed:", e)
def moisture_pct():
    raw = sum(adc.read() for _ in range(20)) // 20
    pct = (DRY - raw) * 100 / (DRY - WET)
    return round(max(0, min(100, pct)), 1), raw
def read_lux():
    i2c.writeto(35, b'\x01')
    i2c.writeto(35, b'\x10')
    time.sleep_ms(180)
    d = i2c.readfrom(35, 2)
    return round((d[0] << 8 | d[1]) / 1.2, 1)
def read_climate():
    # Returns (temp C, humidity %). Pressure is discarded.
    # This driver returns integers: temp x100, humidity x1024.
    t, p, h = bme.read_compensated_data()
    return round(t / 100, 1), round(h / 1024, 1)
# ---- wifi ----
def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASS)
    for _ in range(20):
        if wlan.isconnected():
            return True
        wdt.feed()             # keep the watchdog happy while we wait to connect
        time.sleep(1)
    return False
# ---- adafruit io ----
def push(feed, value):
    url = "https://io.adafruit.com/api/v2/{}/feeds/{}/data".format(secrets.AIO_USER, feed)
    try:
        r = urequests.post(url,
            headers={"X-AIO-Key": secrets.AIO_KEY, "Content-Type": "application/json"},
            json={"value": value})
        ok = r.status_code < 300
        r.close()
        return ok
    except Exception as e:
        print("push failed:", feed, e)
        return False
# ---- main loop ----
print("logger starting")
while True:
    led.value(1)
    wdt.feed()
    # If the sensor wasn't found at boot, keep trying each cycle.
    if bme is None:
        try:
            b = bme280.BME280(i2c=i2c, address=BME_ADDR)
            b.read_compensated_data()   # discard first junk sample
            bme = b
            print("bme280 ready")
        except Exception as e:
            print("bme280 init failed:", e)
    # Read each sensor on its own, so if one fails (loose cable, etc.)
    # we still keep the other one's reading for this cycle.
    pct = raw =  None
    try:
        pct, raw = moisture_pct()
        print("moisture {}% (raw {})".format(pct, raw))
    except Exception as e:
        print("moisture read failed:", e)
    lux = None
    try:
        lux = read_lux()
        print("lux {}".format(lux))
    except Exception as e:
        print("light read failed:", e)
    temp = hum = None
    if bme is not None:
        try:
            temp, hum = read_climate()
            print("temp {}C humidity {}%".format(temp, hum))
        except Exception as e:
            print("climate read failed:", e)
    # Send whatever we managed to read.
    try:
        if wifi_connect():
            wdt.feed()
            if pct is not None:
                push("moisture-1", pct)
            if raw is not None:
                push("moisture-raw-1", raw)
            if lux is not None:
                push("light", lux)
            if temp is not None:
                push("temp", temp)
            if hum is not None:
                push("humidity", hum)
        else:
            print("no wifi this cycle")
    except Exception as e:
        print("send failed:", e)
    gc.collect()               # tidy up memory so it doesn't get fragmented over days
    led.value(0)
    sleep_fed(INTERVAL)        # 10-minute wait, feeding the watchdog throughoutx
