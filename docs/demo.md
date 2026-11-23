# Demonstration guide

The mock replays rows from the **held-out test split** and the trained Random Forest scores them live. Only the
timing and mix of the traffic come from the scenario file.

## Scenario `mock_zabbix/scenarios/defense_demo.yaml` (60-second loop, deterministic, seed 2026)

| Offset | Phase | Host | Replayed traffic | Zabbix side |
|---|---|---|---|---|
| 0–10 s | normal | all | BENIGN | — |
| 10–22 s | recon | lan-a-core | 85% port/OS scan, host discovery, vuln scan | Suricata "ET SCAN" problem (+3 s) |
| 22–38 s | ddos | pfsense-edge | 90% SYN/TCP/ICMP flood | firewall states ×5.6; "states > 80%" and "blocked connections" problems |
| 38–48 s | recovery | all | BENIGN | problems recover |
| 48–56 s | web_attack | lan-b-core | 80% SQLi/XSS/command injection/upload | no Zabbix trigger: detected by the model only |
| 56–60 s | cooldown | all | BENIGN | — |

One hour of benign history is available before the scenario starts, so the charts aren't empty.

## Walkthrough (the loop repeats every 60 s)

1. `./scripts/start.sh`, then open `http://localhost:8080`. Overview: 3 hosts, source **up**, scores flat and low.
2. **+10 s.** The LAN A score chart turns red. Within about 10–20 s an incident appears:
   *"Suspected Recon (score 1.00)"*, severity high, with the Suricata problem linked.
3. Open the incident: category distribution, score timeline, anomalous windows with class probabilities.
   **Acknowledge** it with a note (stored locally only).
4. **+22 s.** pfSense DDoS. The incident is critical because the host is tagged `criticality=critical`, and two
   Zabbix problems are linked. Host page: firewall-state and bandwidth metrics spike (context only).
5. **Failure handling.** `./scripts/demo.sh outage 30`: the banner shows the source degraded/down with the
   error. After recovery the worker backfills the gap from its watermark.
6. **Auto-resolve.** Incidents resolve 120 s after the last anomaly, which is longer than the 60 s loop, so they stay open while the scenario keeps repeating.
7. **+48 s.** Web attack on LAN B. No Zabbix trigger fires; the windows the model flags show up on its score
   chart (web recall 0.19 offline).
8. **Model page.** Offline test metrics, per-class table, confusion matrix, and **live agreement** with the
   scenario's ground truth.

Restart the timeline at any time with `./scripts/demo.sh restart`.

## Reference run

- A Recon incident on LAN A (24 anomalous windows), with the Suricata problem linked.
- A DDoS incident on pfSense, with both Zabbix problems linked.
- Outage injection: health went `down` with "history.get: HTTP 503" and recovered automatically.
- Live agreement over 10 min: precision 0.915, recall 0.701, FPR 0.61%.
- In the automated end-to-end test, the 1-hour benign backfill produced **0** false incidents.
