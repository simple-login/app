from app import config
from typing import Optional, List, Tuple

import dns.resolver


def _get_dns_resolver():
    my_resolver = dns.resolver.Resolver()
    my_resolver.nameservers = config.NAMESERVERS

    return my_resolver


def get_ns(hostname) -> [str]:
    try:
        answers = _get_dns_resolver().resolve(hostname, "NS", search=True)
    except Exception:
        return []
    return [a.to_text() for a in answers]


def get_cname_record(hostname) -> Optional[str]:
    """Return the CNAME record if exists for a domain, WITHOUT the trailing period at the end"""
    try:
        answers = _get_dns_resolver().resolve(hostname, "CNAME", search=True)
    except Exception:
        return None

    for a in answers:
        ret = a.to_text()
        return ret[:-1]

    return None


def get_mx_domains(hostname) -> [(int, str)]:
    """return list of (priority, domain name).
    domain name ends with a "." at the end.
    """
    try:
        answers = _get_dns_resolver().resolve(hostname, "MX", search=True)
    except Exception:
        return []

    ret = []

    for a in answers:
        record = a.to_text()  # for ex '20 alt2.aspmx.l.google.com.'
        parts = record.split(" ")

        ret.append((int(parts[0]), parts[1]))

    return ret


_include_spf = "include:"


def get_spf_domain(hostname) -> [str]:
    """return all domains listed in *include:*"""
    try:
        answers = _get_dns_resolver().resolve(hostname, "TXT", search=True)
    except Exception:
        return []

    ret = []

    for a in answers:  # type: dns.rdtypes.ANY.TXT.TXT
        for record in a.strings:
            record = record.decode()  # record is bytes

            if record.startswith("v=spf1"):
                parts = record.split(" ")
                for part in parts:
                    if part.startswith(_include_spf):
                        ret.append(part[part.find(_include_spf) + len(_include_spf) :])

    return ret


def get_txt_record(hostname) -> [str]:
    try:
        answers = _get_dns_resolver().resolve(hostname, "TXT", search=True)
    except Exception:
        return []

    ret = []

    for a in answers:  # type: dns.rdtypes.ANY.TXT.TXT
        for record in a.strings:
            record = record.decode()  # record is bytes

            ret.append(record)

    return ret


def is_mx_equivalent(
    mx_domains: List[Tuple[int, str]], ref_mx_domains: List[Tuple[int, str]]
) -> bool:
    """
    Compare mx_domains with ref_mx_domains to see if they are equivalent.
    mx_domains and ref_mx_domains are list of (priority, domain)

    The priority order is taken into account but not the priority number.
    For example, [(1, domain1), (2, domain2)] is equivalent to [(10, domain1), (20, domain2)]
    """
    mx_domains = sorted(mx_domains, key=lambda priority_domain: priority_domain[0])
    ref_mx_domains = sorted(
        ref_mx_domains, key=lambda priority_domain: priority_domain[0]
    )

    if len(mx_domains) < len(ref_mx_domains):
        return False

    for i in range(0, len(ref_mx_domains)):
        if mx_domains[i][1] != ref_mx_domains[i][1]:
            return False

    return True
