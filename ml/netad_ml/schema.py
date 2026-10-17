"""Dataset schema and label taxonomy.

Single source of truth for raw column names, label mapping and the model
feature list. Shared by training (ml/) and online inference (backend worker).
"""
from __future__ import annotations

LABEL_COL = "Label"

# Exact header of every CSV in data/ (verified identical across all 63 files).
RAW_FEATURES: tuple[str, ...] = (
    "Header_Length", "Protocol Type", "Time_To_Live", "Rate",
    "fin_flag_number", "syn_flag_number", "rst_flag_number", "psh_flag_number",
    "ack_flag_number", "ece_flag_number", "cwr_flag_number",
    "ack_count", "syn_count", "fin_count", "rst_count",
    "HTTP", "HTTPS", "DNS", "Telnet", "SMTP", "SSH", "IRC", "TCP", "UDP",
    "DHCP", "ARP", "ICMP", "IGMP", "IPv", "LLC",
    "Tot sum", "Min", "Max", "AVG", "Std", "Tot size", "IAT", "Number", "Variance",
)
RAW_COLUMNS: tuple[str, ...] = (*RAW_FEATURES, LABEL_COL)

BENIGN = "Benign"

# 34 raw labels (upper-case, as found in the data) -> 8 categories.
LABEL_TO_CATEGORY: dict[str, str] = {
    **{k: "DDoS" for k in (
        "DDOS-RSTFINFLOOD", "DDOS-PSHACK_FLOOD", "DDOS-SYN_FLOOD", "DDOS-UDP_FLOOD",
        "DDOS-TCP_FLOOD", "DDOS-ICMP_FLOOD", "DDOS-SYNONYMOUSIP_FLOOD",
        "DDOS-ACK_FRAGMENTATION", "DDOS-UDP_FRAGMENTATION", "DDOS-ICMP_FRAGMENTATION",
        "DDOS-SLOWLORIS", "DDOS-HTTP_FLOOD")},
    **{k: "DoS" for k in ("DOS-UDP_FLOOD", "DOS-SYN_FLOOD", "DOS-TCP_FLOOD", "DOS-HTTP_FLOOD")},
    **{k: "Mirai" for k in ("MIRAI-GREETH_FLOOD", "MIRAI-GREIP_FLOOD", "MIRAI-UDPPLAIN")},
    **{k: "Recon" for k in (
        "RECON-PINGSWEEP", "RECON-OSSCAN", "RECON-PORTSCAN", "VULNERABILITYSCAN",
        "RECON-HOSTDISCOVERY")},
    **{k: "Spoofing" for k in ("DNS_SPOOFING", "MITM-ARPSPOOFING")},
    "BENIGN": BENIGN,
    **{k: "Web" for k in (
        "BROWSERHIJACKING", "BACKDOOR_MALWARE", "XSS", "UPLOADING_ATTACK",
        "SQLINJECTION", "COMMANDINJECTION")},
    "DICTIONARYBRUTEFORCE": "BruteForce",
}
RAW_LABELS: tuple[str, ...] = tuple(sorted(LABEL_TO_CATEGORY))
CATEGORIES: tuple[str, ...] = ("Benign", "BruteForce", "DDoS", "DoS", "Mirai", "Recon", "Spoofing", "Web")

assert len(LABEL_TO_CATEGORY) == 34
assert set(LABEL_TO_CATEGORY.values()) == set(CATEGORIES)
