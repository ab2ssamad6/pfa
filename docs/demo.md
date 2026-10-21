# Demonstration guide

Everything shown comes from the trained Random Forest scoring rows from the **held-out test split** that the mock
replays. Only the *timing and mix* of the traffic is synthetic (the scenario file); no prediction is fabricated.

## Scenario `mock_zabbix/scenarios/defense_demo.yaml` (12-minute loop, deterministic, seed 2026)

| Offset | Phase | Host | Replayed traffic | Zabbix side |
|---|---|---|---|---|
| 0–3 min | normal | all | BENIGN | — |
| 3–5 min | recon | lan-a-core | 85% port/OS scan, host discovery, vuln scan | Suricata "ET SCAN" problem (+25 s) |
| 5–8 min | ddos | pfsense-edge | 90% SYN/TCP/ICMP flood | firewall states ×5.6; "states > 80%" and "blocked connections" problems |
| 8–10 min | recovery | all | BENIGN | problems recover |
| 10–11 min | web_attack | lan-b-core | 80% SQLi/XSS/command injection/upload | no Zabbix trigger (shows ML-only detection, and its limits) |
| 11–12 min | cooldown | all | BENIGN | — |

One hour of benign history is available before the scenario starts, so the charts aren't empty.

## Walkthrough (about 12 minutes)

1. `./scripts/start.sh`, then open `http://localhost:8080`. Overview: 3 hosts, source **up**, scores flat and low.
2. **+3 min.** The LAN A score chart turns red. Within about 10–20 s an incident appears:
   *"Suspected Recon (score 1.00)"*, severity high, with the Suricata problem linked.
3. Open the incident: category distribution, score timeline, anomalous windows with class probabilities.
   **Acknowledge** it with a note (stored locally only).
4. **+5 min.** pfSense DDoS. The incident is critical because the host is tagged `criticality=critical`, and two
   Zabbix problems are linked. Host page: firewall-state and bandwidth metrics spike (context only).
5. **Failure handling.** `./scripts/demo.sh outage 30`: the banner shows the source degraded/down with the
   error. After recovery the worker backfills the gap from its watermark.
6. **+8–10 min.** Incidents auto-resolve 120 s after the last anomaly.
7. **+10 min.** Web attack on LAN B: few windows are flagged (web recall ≈ 0.19 offline), which honestly
   illustrates the weak class.
8. **Model page.** Offline test metrics, per-class table, confusion matrix, and **live agreement** with the
   scenario's ground truth.

Restart the timeline at any time with `./scripts/demo.sh restart`.

## What was observed in the local integration run (2026-10-20)

- A Recon incident on LAN A (24 anomalous windows), with the Suricata problem linked.
- A DDoS incident on pfSense, with both Zabbix problems linked.
- Outage injection: health went `down` with "history.get: HTTP 503" and recovered automatically.
- Live agreement over 10 min: precision 0.915, recall 0.701, FPR 0.61%.
- In the automated end-to-end test, the 1-hour benign backfill produced **0** false incidents.
