# udsdump

A command-line tool for monitoring **UDS (Unified Diagnostic Services) traffic on CAN buses** — one abstraction layer above `candump`.

While `candump` shows raw CAN frames, `udsdump` works at the UDS service level: it reassembles ISO-TP multi-frame messages, identifies request/response pairs, and outputs one line per complete UDS transaction with decoded metadata (service name, DID, sub-function, NRC, latency).

```
11:04:25.131  0x0680→0x0690  ReadDataByIdentifier          DID=0x0100    req=0x03 rsp=0x22  dt=8.0ms     SF/MF  ok
11:04:25.209  0x0680→0x0690  WriteDataByIdentifier         DID=0x023A    req=0x07 rsp=0x03  dt=12.3ms    MF/SF  ok
11:04:25.308  0x0680→0x0690  DiagnosticSessionControl      sub=0x01      req=0x02 rsp=0x02  dt=5.1ms     SF/SF  ok
11:04:26.416  0x0680→0x0690  ReadDataByIdentifier          DID=0x0200    req=0x03 rsp=0x00              SF     timeout
11:04:26.524  0x0680→0x0690  SecurityAccess                sub=0x01      req=0x02 rsp=0x03  dt=6.7ms     SF/SF  nrc  NRC=0x35(invalidKey)
```

## Features

- **One line per UDS transaction** — request and response combined, regardless of SF or MF
- **ISO-TP reassembly** — handles Single Frame and Multi-Frame messages transparently; `SF/MF` in the output shows the frame type of each direction
- **Parallel conversations** — multiple simultaneous UDS sessions on different ID pairs are handled independently
- **Status metadata** — every line reports the outcome: `ok`, `nrc` (negative response with code and name), or `timeout`
- **Optional raw payload** — `--payload` appends the raw UDS bytes as hex strings
- **JSON output** — `--json` for machine-readable output (only non-empty fields)
- **Flexible ID configuration** — automatic offset mode (default `req + 0x10 = rsp`) or explicit ID pairs

## Requirements

- Python 3.10+
- [python-can](https://python-can.readthedocs.io/) ≥ 4.3
- A CAN interface supported by python-can (SocketCAN, PEAK, Kvaser, virtual, …)

## Installation

Install directly from GitHub:

```bash
pip install git+https://github.com/MyHomeMyData/udsdump.git
```

For local development, clone the repository and install in editable mode:

```bash
git clone https://github.com/MyHomeMyData/udsdump.git
cd udsdump
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

Monitor UDS traffic on `vcan0` with default settings (SocketCAN, ID range `0x600–0x6FF`, response offset `+0x10`):

```bash
udsdump --channel vcan0
```

Monitor specific device pairs (e.g. Viessmann E3 heat pump):

```bash
udsdump --channel can0 --id-pair 0x680:0x690 --id-pair 0x6A1:0x6B1
```

JSON output, piped to `jq` for filtering:

```bash
udsdump --channel can0 --json | jq 'select(.status == "nrc")'
```

## CLI Reference

```
udsdump [options]

CAN interface:
  --interface, -i INTERFACE   python-can interface name  (default: socketcan)
  --channel,   -c CHANNEL     CAN channel                (default: vcan0)
  --bitrate,   -b BITRATE     Bus bitrate in bit/s       (default: 500000)

ID pair configuration (mutually exclusive):
  --id-pair REQ:RSP            Explicit request:response ID pair (hex).
                               May be repeated for multiple pairs.
  --response-offset OFFSET     Response ID = request ID + OFFSET (hex).
                               (default: 0x10)

  --id-range MIN:MAX           CAN ID range to monitor (hex).
                               Used with --response-offset.  (default: 0x600:0x6FF)
                               Ignored when --id-pair is used.

Behaviour:
  --timeout, -t SECONDS        Response timeout in seconds  (default: 1.0)

Output:
  --json                       One JSON object per line instead of text
  --payload                    Append raw UDS payload bytes (hex) to each line
```

### ID pair configuration

**Offset mode (default):** Every CAN ID in `--id-range` is treated as a potential request ID. The corresponding response ID is `request_id + offset`. This covers the common UDS convention and Viessmann E3 devices without any extra configuration.

```bash
# Viessmann E3: request 0x680, response 0x690; request 0x6A1, response 0x6B1; …
udsdump --channel can0 --response-offset 0x10 --id-range 0x680:0x6B1
```

**Explicit pair mode:** Use `--id-pair` when devices do not follow a fixed offset. Multiple `--id-pair` arguments are supported.

```bash
udsdump --channel can0 --id-pair 0x7DF:0x7E8 --id-pair 0x712:0x733
```

## Output Format

### Text (default)

```
HH:MM:SS.mmm  REQ_ID→RSP_ID  ServiceName              [DID=0xNNNN|sub=0xNN]  req=0xNN rsp=0xNN  [dt=N.Nms]  FT  status  [NRC]
```

| Field | Description |
|---|---|
| `HH:MM:SS.mmm` | Timestamp of the request |
| `REQ_ID→RSP_ID` | CAN ID pair (hex) |
| `ServiceName` | UDS service (e.g. `ReadDataByIdentifier`) |
| `DID=0x…` / `sub=0x…` | Data Identifier or sub-function (where applicable) |
| `req=0xNN` / `rsp=0xNN` | Payload length in bytes (hex) |
| `dt=N.Nms` | Round-trip latency; absent on timeout |
| `FT` | Frame type: `SF/SF`, `SF/MF`, `MF/SF`, `MF/MF`, or just `SF`/`MF` on timeout |
| `status` | `ok`, `nrc`, or `timeout` |
| `NRC=0xNN(name)` | NRC code and name on `nrc` status |

With `--payload`, two additional hex fields are appended: `req_data=…  rsp_data=…`.

### JSON

Each transaction is a JSON object on a single line. Only non-empty fields are included.

```json
{"timestamp": 1746789865.131, "request_id": 1664, "response_id": 1680, "service_id": 34, "service_name": "ReadDataByIdentifier", "req_frame_type": "SF", "rsp_frame_type": "MF", "status": "ok", "did": 256, "req_length": 3, "rsp_length": 34, "duration_ms": 8.0}
```

Timeout example:

```json
{"timestamp": 1746789866.416, "request_id": 1664, "response_id": 1680, "service_id": 34, "service_name": "ReadDataByIdentifier", "req_frame_type": "SF", "status": "timeout", "did": 512, "req_length": 3}
```

## Decoded UDS Services

| SID | Service |
|-----|---------|
| 0x10 | DiagnosticSessionControl |
| 0x11 | ECUReset |
| 0x14 | ClearDiagnosticInformation |
| 0x19 | ReadDTCInformation |
| 0x22 | ReadDataByIdentifier |
| 0x27 | SecurityAccess |
| 0x28 | CommunicationControl |
| 0x2E | WriteDataByIdentifier |
| 0x31 | RoutineControl |
| 0x34 | RequestDownload |
| 0x36 | TransferData |
| 0x37 | RequestTransferExit |
| 0x3E | TesterPresent |

Positive responses (`SID + 0x40`) and negative responses (`0x7F`) are matched automatically.

## Library API

`udsdump` can also be used as a Python library:

```python
import asyncio
from udsdump import UDSMonitor

async def main():
    monitor = UDSMonitor(
        interface="socketcan",
        channel="can0",
        explicit_pairs=[(0x680, 0x690)],
        timeout=1.0,
    )

    async for tx in monitor.transactions():
        print(tx.service_name, tx.did, tx.status, tx.duration_ms)

asyncio.run(main())
```

Or with a callback:

```python
monitor.on_transaction(lambda tx: print(tx))
await monitor.run()
```

## Development

```bash
# Install with dev dependencies
pip install -e .
pip install pytest

# Run tests
pytest
```

36 tests cover the ISO-TP reassembler, the UDS decoder, and the transaction manager (pairing, timeouts, parallel sessions, multi-frame handling).

## Acknowledgements

The ISO-TP reassembler is adapted from [E3onCANserver](https://github.com/MyHomeMyData/E3onCANserver) by the same author.

## License

MIT License — see [LICENSE](LICENSE) file.
