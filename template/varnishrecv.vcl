# DO NOT EDIT!
# THIS FILE WILL BE REPLACED
{% for i in cond %}
if(req.http.host {% if i.subdomain %}~ "^((.+?)\.|){{i.hostname}}$"{% else %}== "{{i.hostname}}"{%endif%}){
	set req.backend = {{i.backend.name}};
}else {%- endfor -%}
if(req.http.host == "{{ovzcphost}}"){
	set req.backend = ovzcp;
}else{
	set req.backend = {{nomatch}};
}