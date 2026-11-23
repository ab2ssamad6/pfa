# Connecting a real Zabbix

The backend's only source implementation, `ZabbixJsonRpcAdapter` (`backend/app/sources/zabbix.py`), speaks
standard Zabbix 6.0/7.0 JSON-RPC. Switching from the mock to a real server is configuration only.

## Steps

1. **API token.** In Zabbix, go to *Users → API tokens*, create a token for a read-only user with access to the
   monitored host groups.
2. **Configure** `.env`:
   ```env
   ZABBIX_URL=https://zabbix.example.org/api_jsonrpc.php
   ZABBIX_TOKEN=<token>
   DEMO_TRUTH_URL=          # no ground truth outside the demo
   ```
   Then start only the services you need: `docker compose up -d db api worker web`.
3. **Feature item.** On each host to analyse, create a *Zabbix trapper* item with key `netad.flow.features`
   and type of information *Text*. Feed it one JSON object per window containing the 37 feature names listed in
   `artifacts/models/<version>/metadata.json → features` (the 39 raw names are also accepted). For example:
   ```bash
   zabbix_sender -z zabbix -s pfsense-edge -k netad.flow.features -o '{"Header_Length":20.1,"Rate":2589.4, ...}'
   ```
   On pfSense the windows come from flow aggregation (softflowd / CICFlowMeter-style) pushed with `zabbix_sender`.
4. **Metric items (optional).** The keys listed in `ZABBIX_METRIC_ITEM_KEYS` (default:
   `net.if.in[igb0]`, `net.if.out[igb0]`, `system.cpu.util`, `pfsense.state.table.current`) are ingested for
   display. Adjust the list to your templates (JSON list in env).
5. **Host criticality.** Add the host tag `criticality = critical|high|medium|low`. It feeds incident severity.

## Behavioural notes

| Topic | Behaviour |
|---|---|
| Pagination | By time (`time_from` = last clock, `limit` = `INGEST_PAGE_SIZE`). Duplicates are removed by DB constraints |
| Problem events | `event.get` is re-read with a 1 h lookback (`EVENT_LOOKBACK_SECONDS`) so recoveries update stored problems |
| Errors | HTTP/transport errors mark the source degraded/down with backoff; JSON-RPC errors (e.g. "Not authorised.") are surfaced verbatim in `/api/health` |
| Zabbix 6.0 | Uses only methods and fields common to 6.0 and 7.0 |
| Acknowledgements | Stored in NetAD with the analyst's note |
| Clock skew | Feature timestamps come from Zabbix `clock`; keep the Zabbix server NTP-synchronised |

## Contract tests
`mock_zabbix/tests/test_contract_zabbix_doc.py` replays the request examples from `mock_zabbix/tests/fixtures/zabbix_doc/*.json` and checks the
documented response fields. `backend/tests/test_adapter_contract.py` checks the adapter against the mock,
including paging, auth errors, HTTP 503 and connection failures. Run the second suite against a staging Zabbix
before going live.
