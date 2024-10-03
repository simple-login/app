from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import dns.resolver

from app.config import NAMESERVERS

_include_spf = "include:"


@dataclass
class MxRecord:
    priority: int
    domain: str


def is_mx_equivalent(
    mx_domains: List[MxRecord], ref_mx_domains: List[MxRecord]
) -> bool:
    """
    Compare mx_domains with ref_mx_domains to see if they are equivalent.
    mx_domains and ref_mx_domains are list of (priority, domain)

    The priority order is taken into account but not the priority number.
    For example, [(1, domain1), (2, domain2)] is equivalent to [(10, domain1), (20, domain2)]
    """
    mx_domains = sorted(mx_domains, key=lambda x: x.priority)
    ref_mx_domains = sorted(ref_mx_domains, key=lambda x: x.priority)

    if len(mx_domains) < len(ref_mx_domains):
        return False

    for actual, expected in zip(mx_domains, ref_mx_domains):
        if actual.domain != expected.domain:
            return False

    return True


class DNSClient(ABC):
    @abstractmethod
    def get_cname_record(self, hostname: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_mx_domains(self, hostname: str) -> List[MxRecord]:
        pass

    def get_spf_domain(self, hostname: str) -> List[str]:
        """
        return all domains listed in *include:*
        """
        try:
            records = self.get_txt_record(hostname)
            ret = []
            for record in records:
                if record.startswith("v=spf1"):
                    parts = record.split(" ")
                    for part in parts:
                        if part.startswith(_include_spf):
                            ret.append(
                                part[part.find(_include_spf) + len(_include_spf) :]
                            )
            return ret
        except Exception:
            return []

    @abstractmethod
    def get_txt_record(self, hostname: str) -> List[str]:
        pass


class NetworkDNSClient(DNSClient):
    def __init__(self, nameservers: List[str]):
        self._resolver = dns.resolver.Resolver()
        self._resolver.nameservers = nameservers

    def get_cname_record(self, hostname: str) -> Optional[str]:
        """
        Return the CNAME record if exists for a domain, WITHOUT the trailing period at the end
        """
        try:
            answers = self._resolver.resolve(hostname, "CNAME", search=True)
            for a in answers:
                ret = a.to_text()
                return ret[:-1]
        except Exception:
            return None

    def get_mx_domains(self, hostname: str) -> List[MxRecord]:
        """
        return list of (priority, domain name) sorted by priority (lowest priority first)
        domain name ends with a "." at the end.
        """
        try:
            answers = self._resolver.resolve(hostname, "MX", search=True)
            ret = []
            for a in answers:
                record = a.to_text()  # for ex '20 alt2.aspmx.l.google.com.'
                parts = record.split(" ")
                ret.append(MxRecord(priority=int(parts[0]), domain=parts[1]))
            return sorted(ret, key=lambda x: x.priority)
        except Exception:
            return []

    def get_txt_record(self, hostname: str) -> List[str]:
        try:
            answers = self._resolver.resolve(hostname, "TXT", search=False)
            ret = []
            for a in answers:  # type: dns.rdtypes.ANY.TXT.TXT
                for record in a.strings:
                    ret.append(record.decode())
            return ret
        except Exception:
            return []


class InMemoryDNSClient(DNSClient):
    def __init__(self):
        self.cname_records: dict[str, Optional[str]] = {}
        self.mx_records: dict[str, List[MxRecord]] = {}
        self.spf_records: dict[str, List[str]] = {}
        self.txt_records: dict[str, List[str]] = {}

    def set_cname_record(self, hostname: str, cname: str):
        self.cname_records[hostname] = cname

    def set_mx_records(self, hostname: str, mx_list: List[MxRecord]):
        self.mx_records[hostname] = mx_list

    def set_txt_record(self, hostname: str, txt_list: List[str]):
        self.txt_records[hostname] = txt_list

    def get_cname_record(self, hostname: str) -> Optional[str]:
        return self.cname_records.get(hostname)

    def get_mx_domains(self, hostname: str) -> List[MxRecord]:
        mx_list = self.mx_records.get(hostname, [])
        return sorted(mx_list, key=lambda x: x.priority)

    def get_txt_record(self, hostname: str) -> List[str]:
        return self.txt_records.get(hostname, [])


def get_network_dns_client() -> NetworkDNSClient:
    return NetworkDNSClient(NAMESERVERS)


def get_mx_domains(hostname: str) -> List[MxRecord]:
    return get_network_dns_client().get_mx_domains(hostname)
