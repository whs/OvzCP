# DO NOT EDIT!
# THIS FILE WILL BE REPLACED
# Generated for varnish {{".".join(version)}}

{% for i in backend %}
backend {{i.name}}{
	{% if prefix %}set backend{% endif %}.host = "{{i.vm.vz.ip}}";
	{% if prefix %}set backend{% endif %}.port = "{{i.port}}";
}
{% endfor %}
{% for i in [21215,21216,21217,21218] %}
backend ovzcp_{{i}}{
	{% if prefix %}set backend{% endif %}.host = "127.0.0.1";
	{% if prefix %}set backend{% endif %}.port = "{{i}}";
}
{% endfor %}
director ovzcp round-robin{
{% for i in [21215,21216,21217,21218] %}
	{ .backend = ovzcp_{{i}}; }
{% endfor %}
}
