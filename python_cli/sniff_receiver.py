#!/usr/bin/env python3

# Written by Sultan Qasim Khan
# Copyright (c) 2018-2019, NCC Group plc
# Released as open source under GPLv3

import argparse, sys
from pcap import PcapBleWriter
from sniffle_hw import SniffleHW, BLE_ADV_AA, PacketMessage, DebugMessage, StateMessage
from packet_decoder import DPacketMessage, AdvaMessage, AdvDirectIndMessage, AdvExtIndMessage, ConnectIndMessage

# global variable to access hardware
hw = None

# global variable for pcap writer
pcwriter = None

# if true, filter on the first advertiser MAC seen
# triggered through "-m top" option
# should be paired with an RSSI filter
_delay_top_mac = False
_rssi_min = 0
_allow_hop3 = True

def main():
    aparse = argparse.ArgumentParser(description="Host-side receiver for Sniffle BLE5 sniffer")
    aparse.add_argument("-s", "--serport", default="/dev/ttyACM0", help="Sniffer serial port name")
    aparse.add_argument("-c", "--advchan", default=37, choices=[37, 38, 39], type=int,
            help="Advertising channel to listen on")
    aparse.add_argument("-p", "--pause", action="store_const", default=False, const=True,
            help="Pause sniffer after disconnect")
    aparse.add_argument("-r", "--rssi", default=-80, type=int,
            help="Filter packets by minimum RSSI")
    aparse.add_argument("-m", "--mac", default=None, help="Filter packets by advertiser MAC")
    aparse.add_argument("-a", "--advonly", action="store_const", default=False, const=True,
            help="Sniff only advertisements, don't follow connections")
    aparse.add_argument("-e", "--extadv", action="store_const", default=False, const=True,
            help="Capture BT5 extended (auxiliary) advertising")
    aparse.add_argument("-H", "--hop", action="store_const", default=False, const=True,
            help="Hop primary advertising channels in extended mode")
    aparse.add_argument("-l", "--longrange", action="store_const", default=False, const=True,
            help="Use long range (coded) PHY for primary advertising")
    aparse.add_argument("-o", "--output", default=None, help="PCAP output file name")
    args = aparse.parse_args()

    # Sanity check argument combinations
    if args.hop and args.mac is None:
        print("Primary adv. channel hop requires a MAC address specified!", file=sys.stderr)
        return
    if args.longrange and not args.extadv:
        print("Long-range PHY only supported in extended advertising!", file=sys.stderr)
        return
    if args.longrange and args.hop:
        # this would be pointless anyway, since long range always uses extended ads
        print("Primary ad channel hopping unsupported on long range PHY!", file=sys.stderr)
        return

    global hw
    hw = SniffleHW(args.serport)

    # set the advertising channel (and return to ad-sniffing mode)
    hw.cmd_chan_aa_phy(args.advchan, BLE_ADV_AA, 2 if args.longrange else 0)

    # set whether or not to pause after sniffing
    hw.cmd_pause_done(args.pause)

    # set up endTrim
    if args.advonly:
        hw.cmd_endtrim(0xB0)
    else:
        hw.cmd_endtrim(0x10)

    # configure RSSI filter
    global _rssi_min
    _rssi_min = args.rssi
    hw.cmd_rssi(args.rssi)

    # disable 37/38/39 hop in extended mode unless overridden
    global _allow_hop3
    if args.extadv and not args.hop:
        _allow_hop3 = False

    # configure MAC filter
    global _delay_top_mac
    if args.mac is None:
        hw.cmd_mac()
    elif args.mac == "top":
        hw.cmd_mac()
        _delay_top_mac = True
    else:
        try:
            macBytes = [int(h, 16) for h in reversed(args.mac.split(":"))]
            if len(macBytes) != 6:
                raise Exception("Wrong length!")
        except:
            print("MAC must be 6 colon-separated hex bytes", file=sys.stderr)
            return
        hw.cmd_mac(macBytes, _allow_hop3)

    # configure BT5 extended (aux/secondary) advertising
    hw.cmd_auxadv(args.extadv)

    # zero timestamps and flush old packets
    hw.mark_and_flush()

    global pcwriter
    if not (args.output is None):
        pcwriter = PcapBleWriter(args.output)

    while True:
        msg = hw.recv_and_decode()
        print_message(msg)

def print_message(msg):
    if isinstance(msg, PacketMessage):
        print_packet(msg)
    elif isinstance(msg, DebugMessage):
        print(msg)
    elif isinstance(msg, StateMessage):
        print(msg)
    print()

def print_packet(pkt):
    if pcwriter:
        pcwriter.write_packet(int(pkt.ts_epoch * 1000000), pkt.aa, pkt.chan, pkt.rssi, pkt.body)

    # Further decode and print the packet
    dpkt = DPacketMessage.decode(pkt)
    print(dpkt)

    # React to the packet
    if isinstance(dpkt, AdvaMessage) or isinstance(dpkt, AdvDirectIndMessage) or (
            isinstance(dpkt, AdvExtIndMessage) and dpkt.AdvA is not None):
        _dtm(dpkt.AdvA)

    if isinstance(dpkt, ConnectIndMessage):
        # PCAP write is already done here, safe to update cur_aa
        hw.decoder_state.cur_aa = dpkt.aa

# If we are in _delay_top_mac mode and received a high RSSI advertisement,
# lock onto it
def _dtm(adva):
    global _delay_top_mac
    if _delay_top_mac:
        hw.cmd_mac(adva, _allow_hop3)
        if _allow_hop3:
            # RSSI filter is still useful for extended advertisements,
            # as my MAC filtering logic is less effective
            # Thus, only disable it when we're doing 37/38/39 hops
            #   (ie. when we [also] want legacy advertisements)
            hw.cmd_rssi()
        _delay_top_mac = False

if __name__ == "__main__":
    main()
