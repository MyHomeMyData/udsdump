# udsdump

A command-line tool for monitoring **UDS (Unified Diagnostic Services) traffic on CAN buses** — one abstraction layer above `candump`.

While `candump` shows raw CAN frames, `udsdump` works at the UDS service level: it reassembles ISO-TP multi-frame messages, identifies request/response pairs, and outputs one line per complete UDS transaction with decoded metadata (service name, DID, sub-function, NRC, latency).

```
11:04:25.131  0x0680→0x0690  ReadDataByIdentifier          DID=0x0100 (256)    req=0x03 rsp=0x22  dt=8.0ms     SF/MF  ok
11:04:25.209  0x0680→0x0690  WriteDataByIdentifier         DID=0x023A (570)    req=0x07 rsp=0x03  dt=12.3ms    MF/SF  ok
11:04:25.308  0x0680→0x0690  DiagnosticSessionControl      sub=0x01            req=0x02 rsp=0x02  dt=5.1ms     SF/SF  ok
11:04:26.416  0x0680→0x0690  ReadDataByIdentifier          DID=0x0200 (512)    req=0x03 rsp=0x00               SF     timeout
11:04:26.524  0x0680→0x0690  SecurityAccess                sub=0x01            req=0x02 rsp=0x03  dt=6.7ms     SF/SF  nrc  NRC=0x35(invalidKey)
```

## Features

- **One line per UDS transaction** — request and response combined, regardless of SF or MF
- **ISO-TP reassembly** — handles Single Frame and Multi-Frame messages transparently; `SF/MF` in the output shows the frame type of each direction
- **Parallel conversations** — multiple simultaneous UDS sessions on different ID pairs are handled independently
- **Status metadata** — every line reports the outcome: `ok`, `nrc` (negative response with code and name), or `timeout`
- **NRC 0x78 handling** — ResponsePending is treated correctly: the timeout is restarted, the transaction stays open, and the final `pending_count` is reported
- **Traffic statistics** — periodic and final summary with latency percentiles, success rates, and optional breakdown by ID pair and/or service
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

Statistics only, printed every 5 minutes:

```bash
udsdump --channel can0 --stats-interval 300 --no-transactions
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
  --ignore-requesters IDS      Comma-separated hex CAN IDs to exclude as
                               requesters (e.g. 0x691,0x696).

Behaviour:
  --timeout, -t SECONDS        Response timeout in seconds  (default: 1.0)

Transaction output:
  --json                       One JSON object per line instead of text
  --payload                    Append raw UDS payload bytes (hex) to each line
  --no-transactions            Suppress per-transaction output (statistics only)

Statistics:
  --stats-interval N           Print periodic statistics every N seconds
  --stats-breakdown KEY        Break down statistics by: pair, service, or pair,service
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

**Ignoring specific requesters:** Some CAN nodes send requests that are outside the monitored topology (e.g. they communicate with a peer whose response arrives on a different ID than expected). Use `--ignore-requesters` to exclude them entirely.

```bash
# Viessmann E3: suppress noise from 0x691 and 0x696
udsdump --channel can0 --ignore-requesters 0x691,0x696
```

## Output Format

### Text (default)

```
HH:MM:SS.mmm  REQ_ID→RSP_ID  ServiceName              [DID=0xNNNN (DDD)|sub=0xNN]  req=0xNN rsp=0xNN  [dt=N.Nms]  FT  status  [NRC]
```

| Field | Description |
|---|---|
| `HH:MM:SS.mmm` | Timestamp of the request |
| `REQ_ID→RSP_ID` | CAN ID pair (hex) |
| `ServiceName` | UDS service (e.g. `ReadDataByIdentifier`) |
| `DID=0x… (DDD)` | Data Identifier in hex and decimal |
| `sub=0x…` | Sub-function where applicable |
| `req=0xNN` / `rsp=0xNN` | Payload length in bytes (hex) |
| `dt=N.Nms` | Round-trip latency; absent on timeout |
| `FT` | Frame type: `SF/SF`, `SF/MF`, `MF/SF`, `MF/MF`, or just `SF`/`MF` on timeout |
| `status` | `ok`, `nrc`, or `timeout` |
| `NRC=0xNN(name)` | NRC code and name on `nrc` status |
| `pending×N` | Number of NRC 0x78 (ResponsePending) received before final answer |

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

## Statistics

When any `--stats-*` flag or `--no-transactions` is set, udsdump collects traffic statistics. Transaction lines are written to **stdout**; statistics are written to **stderr** — the two streams never mix, so JSON piping remains clean.

A final summary is always printed on `Ctrl+C`.

### Periodic intervals

```bash
# Print stats every 60 seconds, with breakdown by ID pair
udsdump --channel can0 --stats-interval 60 --stats-breakdown pair
```

```
────────────────────────────────────────────────────────────────────────────────
Stats [11:05:00 – 11:06:00] (60s)
Transactions   total=28    ok=26    nrc=1    timeout=1    rate=0.47/s  success=92.9%
  NRC            conditionsNotCorrect=1
Latency (ok)   min=5.1ms  mean=14.3ms  median=12.1ms  p95=38.2ms  max=45.2ms
By ID pair:
  0x0680→0x0690   ok=24   nrc=1   timeout=1    min=5.1ms  mean=14.3ms  ...
  0x06A1→0x06B1   ok=2    nrc=0   timeout=0    min=6.2ms  mean=8.1ms   ...
────────────────────────────────────────────────────────────────────────────────
```

### Final summary

```
════════════════════════════════════════════════════════════════════════════════
Summary (runtime: 5m 23s)
Transactions   total=142   ok=135   nrc=3    timeout=2    rate=0.44/s  success=95.1%
  NRC            conditionsNotCorrect=2  invalidKey=1
  Pending 0x78   4 transaction(s)
Latency (ok)   min=4.2ms  mean=18.7ms  median=12.3ms  p95=89.1ms  max=312.5ms
By service:
  ReadDataByIdentifier      ok=115  nrc=2   timeout=1    min=4.2ms  mean=15.1ms  p95=89.1ms  max=312.5ms
  TesterPresent             ok=20   nrc=0   timeout=0    min=4.5ms  mean=5.3ms   p95=7.2ms   max=8.1ms
  DiagnosticSessionControl  ok=5    nrc=1   timeout=1    min=12.1ms mean=21.3ms  p95=45.2ms  max=48.0ms
════════════════════════════════════════════════════════════════════════════════
```

### Statistics-only mode

Suppress transaction lines entirely and collect a summary over the full run:

```bash
udsdump --channel can0 --no-transactions --stats-breakdown pair,service
```

Or combine with periodic output:

```bash
udsdump --channel can0 --no-transactions --stats-interval 300 --stats-breakdown service
```

### Combining with JSON

Statistics always appear as human-readable text on stderr, regardless of `--json`. This allows clean downstream processing:

```bash
# JSON transactions to file, stats visible on terminal
udsdump --channel can0 --json --stats-interval 60 > transactions.jsonl

# Filter NRC events while monitoring stats
udsdump --channel can0 --json --stats-breakdown pair | jq 'select(.status == "nrc")'
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

81 tests cover the ISO-TP reassembler, the UDS decoder, the transaction manager (pairing, timeouts, NRC 0x78, parallel sessions, multi-frame handling), the statistics collector, and the ignore-requesters filter.

## Acknowledgements

The ISO-TP reassembler is adapted from [E3onCANserver](https://github.com/MyHomeMyData/E3onCANserver) by the same author.

## Changelog

### 0.1.0 — 2026-05-11

- Initial release
- ISO-TP reassembly (SF and MF), one line per UDS transaction
- NRC 0x78 (ResponsePending) handling: timeout is restarted, transaction stays open, final `pending_count` is reported
- Traffic statistics with periodic intervals and final summary; optional breakdown by ID pair and/or service
- `--ignore-requesters` to suppress noisy requester IDs whose responses never arrive
- JSON output (`--json`), raw payload option (`--payload`)
- 81 tests

## License
MIT License

Copyright (c) 2026 MyHomeMyData <juergen.bonfert@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
