#!/bin/bash
# DO NOT MANUALLY EDIT sysconf/vmfw.sh
# WILL BE REGENRATED BY OvzCP
#
# You may edit in templates/vmfw.sh
# then run `python vmfw.py` as root to update afterward

function ipfw {
	iptables -t nat -A PREROUTING -p tcp -d $5 --dport $3 -j DNAT --to $1:$2 -m state --state NEW,ESTABLISHED,RELATED
	iptables -t nat -A POSTROUTING -s $1 -o $4 -j ACCEPT -m state --state NEW,ESTABLISHED,RELATED
}
function dmz {
	iptables -t nat -A PREROUTING -p tcp -d $3 -j DNAT --to $1 -m state --state NEW,ESTABLISHED,RELATED
	iptables -t nat -A POSTROUTING -s $1 -o $2 -j ACCEPT -m state --state NEW,ESTABLISHED,RELATED
}

iptables -t nat --flush
iptables -t nat -A POSTROUTING -j MASQUERADE --source {{vmip}}0/255.255.0.0

{%- for i in port %}
{%- if i.outport == -1 %}
dmz {{i.vm.vz.ip}} {{i.iface}} {{ip[i.iface]}}
{%- else %}
ipfw {{i.vm.vz.ip}} {{i.port}} {{i.outport}} {{i.iface}} {{ip[i.iface]}}
{%- endif %}
{%- endfor %}