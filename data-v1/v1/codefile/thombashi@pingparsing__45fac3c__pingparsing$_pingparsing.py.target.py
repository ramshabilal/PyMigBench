# encoding: utf-8

"""
.. codeauthor:: Tsuyoshi Hombashi <gogogo.vm@gmail.com>
"""

from __future__ import absolute_import

import re

import typepy
import pyparsing as pp

from .error import EmptyPingStaticticsError
from .error import PingStaticticsHeaderNotFoundError


def _to_unicode(text):
    try:
        return text.decode("ascii")
    except AttributeError:
        return text


class PingParsing(object):
    """
    Parser class to parsing ping command output.
    """

    def __init__(self):
        self.destination_host = ""
        self.ping_option = ""

        self.__initialize_parse_result()

    @property
    def packet_transmit(self):
        """
        :return: Number of packets transmitted.
        :rtype: int
        """

        return self.__packet_transmit

    @property
    def packet_receive(self):
        """
        :return: Number of packets received.
        :rtype: int
        """

        return self.__packet_receive

    @property
    def packet_loss(self):
        """
        :return: Percentage of packet loss [%].
        :rtype: float
        """

        return self.__packet_loss

    @property
    def rtt_min(self):
        """
        :return: Minimum round trip time of transmitted ICMP packets [ms].
        :rtype: float
        """

        return self.__rtt_min

    @property
    def rtt_avg(self):
        """
        :return: Average round trip time of transmitted ICMP packets [ms].
        :rtype: float
        """

        return self.__rtt_avg

    @property
    def rtt_max(self):
        """
        :return: Maximum round trip time of transmitted ICMP packets [ms].
        :rtype: float
        """

        return self.__rtt_max

    @property
    def rtt_mdev(self):
        """
        :return: Standard deviation of transmitted ICMP packets (Linux only).
        :rtype: float
        """

        return self.__rtt_mdev

    def as_dict(self):
        """
        :return: Parsed result as a dictionary.
        :rtype: dict
        """

        return {
            "packet_transmit": self.packet_transmit,
            "packet_receive": self.packet_receive,
            "packet_loss": self.packet_loss,
            "rtt_min": self.rtt_min,
            "rtt_avg": self.rtt_avg,
            "rtt_max": self.rtt_max,
            "rtt_mdev": self.rtt_mdev,
        }

    def parse(self, ping_message):
        """
        Parse ping command output.
        You can get parsing results by attributes:

            - :py:attr:`.packet_transmit`
            - :py:attr:`.packet_receive`
            - :py:attr:`.packet_loss`
            - :py:attr:`.rtt_min`
            - :py:attr:`.rtt_avg`
            - :py:attr:`.rtt_max`
            - :py:attr:`.rtt_mdev`

        Or you can get as a dictionary by :py:meth:`.as_dict`

        :param str ping_message: String of ping command output.
        """

        self.__initialize_parse_result()

        if typepy.is_null_string(ping_message):
            return

        try:
            self.__parse_linux_ping(ping_message)
            return
        except PingStaticticsHeaderNotFoundError:
            pass

        self.__parse_windows_ping(ping_message)

    def __find_ststs_head_line_idx(self, line_list, re_stats_header):
        for i, line in enumerate(line_list):
            if re_stats_header.search(line):
                break
        else:
            raise PingStaticticsHeaderNotFoundError(
                "ping statistics not found")

        return i

    def __validate_stats_body(self, body_line_list):
        if typepy.is_empty_sequence(body_line_list):
            raise EmptyPingStaticticsError("ping statistics is empty")

    def __parse_windows_ping(self, ping_message):
        line_list = _to_unicode(ping_message).splitlines()

        i = self.__find_ststs_head_line_idx(
            line_list, re.compile("^Ping statistics for "))

        body_line_list = line_list[i + 1:]
        self.__validate_stats_body(body_line_list)
        packet_line = body_line_list[0].strip()
        packet_pattern = (
            pp.Literal("Packets: Sent = ") +
            pp.Word(pp.nums) +
            pp.Literal(", Received = ") +
            pp.Word(pp.nums) +
            pp.Literal(", Lost = ") +
            pp.Word(pp.nums) + "(" +
            pp.Word(pp.nums + ".")
        )
        parse_list = packet_pattern.parseString(_to_unicode(packet_line))
        self.__packet_transmit = int(parse_list[1])
        self.__packet_receive = int(parse_list[3])
        self.__packet_loss = float(parse_list[7])

        try:
            rtt_line = body_line_list[2].strip()
        except IndexError:
            return
        if typepy.is_null_string(rtt_line):
            return
        rtt_pattern = (
            pp.Literal("Minimum = ") +
            pp.Word(pp.nums) +
            pp.Literal("ms, Maximum = ") +
            pp.Word(pp.nums) +
            pp.Literal("ms, Average = ") +
            pp.Word(pp.nums)
        )
        try:
            parse_list = rtt_pattern.parseString(_to_unicode(rtt_line))
        except pp.ParseBaseException:
            return

        self.__rtt_min = float(parse_list[1])
        self.__rtt_avg = float(parse_list[5])
        self.__rtt_max = float(parse_list[3])

    def __parse_linux_ping(self, ping_message):
        line_list = _to_unicode(ping_message).splitlines()

        i = self.__find_ststs_head_line_idx(
            line_list, re.compile("--- .* ping statistics ---"))

        body_line_list = line_list[i + 1:]
        self.__validate_stats_body(body_line_list)

        packet_line = body_line_list[0]
        packet_pattern = (
            pp.Word(pp.nums) +
            pp.Literal("packets transmitted,") +
            pp.Word(pp.nums) +
            pp.Literal("received,") +
            pp.SkipTo(pp.Word(pp.nums + ".%") + pp.Literal("packet loss")) +
            pp.Word(pp.nums + ".") +
            pp.Literal("% packet loss")
        )
        parse_list = packet_pattern.parseString(_to_unicode(packet_line))
        self.__packet_transmit = int(parse_list[0])
        self.__packet_receive = int(parse_list[2])
        self.__packet_loss = float(parse_list[-2])

        try:
            rtt_line = body_line_list[1]
        except IndexError:
            return
        if typepy.is_null_string(rtt_line):
            return

        rtt_pattern = (
            pp.Literal("rtt min/avg/max/mdev =") +
            pp.Word(pp.nums + ".") + "/" +
            pp.Word(pp.nums + ".") + "/" +
            pp.Word(pp.nums + ".") + "/" +
            pp.Word(pp.nums + ".") +
            pp.Word(pp.nums + "ms")
        )
        try:
            parse_list = rtt_pattern.parseString(_to_unicode(rtt_line))
        except pp.ParseBaseException:
            return

        self.__rtt_min = float(parse_list[1])
        self.__rtt_avg = float(parse_list[3])
        self.__rtt_max = float(parse_list[5])
        self.__rtt_mdev = float(parse_list[7])

    def __initialize_parse_result(self):
        self.__packet_transmit = None
        self.__packet_receive = None
        self.__packet_loss = None
        self.__rtt_min = None
        self.__rtt_avg = None
        self.__rtt_max = None
        self.__rtt_mdev = None
