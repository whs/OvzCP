#!/bin/bash
# DO NOT MANUALLY EDIT
# WILL BE REGENRATED BY OvzCP

function ipfw {
	iptables -t nat -A PREROUTING -p tcp -d $5 --dport $3 -j DNAT --to $1:$2
	iptables -t nat -A POSTROUTING -s $1 -o $4 -j ACCEPT
}

iptables -t nat --flush
iptables -t nat -A POSTROUTING -j MASQUERADE

{% for i in port %}ipfw {{i.vm.vz.ip}} {{i.port}} {{i.outport}} {{i.iface}} {{ip[i.iface]}}
{% endfor %}