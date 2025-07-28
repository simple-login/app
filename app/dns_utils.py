from abc import ABC, abstractmethod
from typing import List, Optional

import dns.resolver

from app.config import NAMESERVERS

_include_spf = "include:"


class DNSClient(ABC):
    @abstractmethod
    def get_cname_record(self, hostname: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_a_record(self, hostname: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_mx_domains(self, hostname: str) -> dict[int, list[str]]:
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

    def get_a_record(self, hostname: str) -> Optional[str]:
        """
        Return the A RECORD if exists for a domain
        """
        try:
            answers = self._resolver.resolve(hostname, "A", search=True)
            for a in answers:
                ret = a.to_text()
                return ret
        except Exception:
            return None

    def get_mx_domains(self, hostname: str) -> dict[int, list[str]]:
        """
        return list of (priority, domain name) sorted by priority (lowest priority first)
        domain name ends with a "." at the end.
        """
        ret = {}
        try:
            answers = self._resolver.resolve(hostname, "MX", search=True)
            for a in answers:
                record = a.to_text()  # for ex '20 alt2.aspmx.l.google.com.'
                parts = record.split(" ")
                prio = int(parts[0])
                if prio not in ret:
                    ret[prio] = []
                ret[prio].append(parts[1])
        except Exception:
            pass
        return ret

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
        self.a_records: dict[str, Optional[str]] = {}
        self.mx_records: dict[int, dict[int, list[str]]] = {}
        self.spf_records: dict[str, List[str]] = {}
        self.txt_records: dict[str, List[str]] = {}

    def set_cname_record(self, hostname: str, cname: str):
        self.cname_records[hostname] = cname

    def set_a_record(self, hostname: str, a_record: str):
        self.a_records[hostname] = a_record

    def set_mx_records(self, hostname: str, mx_list: dict[int, list[str]]):
        self.mx_records[hostname] = mx_list

    def set_txt_record(self, hostname: str, txt_list: List[str]):
        self.txt_records[hostname] = txt_list

    def get_cname_record(self, hostname: str) -> Optional[str]:
        return self.cname_records.get(hostname)

    def get_a_record(self, hostname: str) -> Optional[str]:
        return self.a_records.get(hostname)

    def get_mx_domains(self, hostname: str) -> dict[int, list[str]]:
        return self.mx_records.get(hostname, {})

    def get_txt_record(self, hostname: str) -> List[str]:
        return self.txt_records.get(hostname, [])


global_dns_client: Optional[DNSClient] = None


def get_network_dns_client() -> DNSClient:
    global global_dns_client
    if global_dns_client is not None:
        return global_dns_client
    return NetworkDNSClient(NAMESERVERS)


def set_global_dns_client(dns_client: Optional[DNSClient]):
    global global_dns_client
    global_dns_client = dns_client


def get_mx_domains(hostname: str) -> dict[int, list[str]]:
    return get_network_dns_client().get_mx_domains(hostname)


def get_a_record(hostname: str) -> Optional[str]:
    return get_network_dns_client().get_a_record(hostname)
