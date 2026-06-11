import time, sys

try:
    from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS
except ImportError:
    print("scservo_sdk not found, trying scsservo_sdk")
    sys.exit(1)

BAUD = 1000000
ADDR_PRESENT_POS = 56
LEN_PRESENT_POS  = 2

EXPECTED = {
    "/dev/ttyACM0": {"name": "right arm", "ids": [1,2,3,4,5,6]},
    "/dev/ttyACM1": {"name": "base",      "ids": [8,9,10,11]},
    "/dev/ttyACM2": {"name": "left arm",  "ids": [1,2,3,4,5,6]},
}

for port, exp in EXPECTED.items():
    ph = PortHandler(port)
    found = []
    if not ph.openPort():
        print(f"{port} [{exp['name']}]: CANNOT OPEN PORT")
        continue
    ph.setBaudRate(BAUD)
    pkt = PacketHandler(0)   # protocol 0 = SCS/Feetech
    for mid in range(1, 12):
        val, result, err = pkt.read2ByteTxRx(ph, mid, ADDR_PRESENT_POS)
        if result == COMM_SUCCESS:
            found.append(mid)
        time.sleep(0.01)
    ph.closePort()

    missing = [i for i in exp["ids"] if i not in found]
    extra   = [i for i in found if i not in exp["ids"]]
    status  = "OK" if not missing and not extra else "MISMATCH"
    print(f"\n{port}  [{exp['name']}]")
    print(f"  found:    {found}")
    print(f"  expected: {exp['ids']}")
    print(f"  status:   {status}")
    if missing: print(f"  MISSING:  {missing}")
    if extra:   print(f"  EXTRA:    {extra}")
