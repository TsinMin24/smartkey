# 最小固件：纯 BLE + 按键，无屏幕
import _bleio
import adafruit_ble
import digitalio
import gc
import microcontroller
import time
from adafruit_ble.advertising import Advertisement
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

KEY_PINS = [microcontroller.pin.P0_31, microcontroller.pin.P0_29,
            microcontroller.pin.P1_15, microcontroller.pin.P1_13, microcontroller.pin.P1_11]
DB = 3

btns = []
for p in KEY_PINS:
    b = digitalio.DigitalInOut(p)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    btns.append(b)
st = [True]*5; ct = [0]*5
if not btns[0].value: _bleio.adapter.erase_bonding()

ble = adafruit_ble.BLERadio()
ble.name = "SmartKey"
uart = UARTService()
adv = ProvideServicesAdvertisement(uart)
sr = Advertisement(); sr.complete_name = "SmartKey"
ble.start_advertising(adv, sr)

wc = False; fr = 0
while True:
    fr += 1
    if not ble.connected and not ble.advertising: ble.start_advertising(adv, sr)
    if ble.connected and not wc: wc = True; uart.write(b"CONNECTED\n")
    elif not ble.connected and wc: wc = False
    if ble.connected and uart.in_waiting:
        ln = uart.readline()
        if ln:
            try:
                cmd = ln.decode("utf-8","ignore").strip()
                if cmd == "PING": uart.write(b"PONG\n")
            except: pass
    cv = [b.value for b in btns]
    for i in range(5):
        if cv[i] != st[i]:
            ct[i] += 1
            if ct[i] >= DB:
                st[i] = cv[i]; ct[i] = 0
                if not st[i]:
                    if ble.connected: uart.write(("DOWN,%d\n"%(i+1)).encode())
                else:
                    if ble.connected: uart.write(("UP,%d\n"%(i+1)).encode())
        else: ct[i] = 0
    if fr % 30 == 0: gc.collect()
    time.sleep(0.015)
