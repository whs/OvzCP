<?php
if(!extension_loaded("curl")) die("curl not found");
if(!extension_loaded("json")) die("json not found");

class CloudCP{
	private $curl, $username;
	public $server;
	public function __construct() { 
		$this->curl = curl_init();
		curl_setopt_array($this->curl, array(
			CURLOPT_CUSTOMREQUEST => "POST",
			CURLOPT_USERAGENT => "PHP-CloudCP/1.0",
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_HTTPAUTH => CURLAUTH_DIGEST,
		));
	} 
	public function login($user, $pass=""){
		if (is_array($user)){
			$pass = $user[1];
			$user = $user[0];
		}
		$this->username = $user;
		curl_setopt($this->curl, CURLOPT_USERPWD, $user.":".$pass);
	}
	public function upload($file, $overwrite=false, $path="/", $name=""){
		if(!$this->username) Throw new Exception("Not logged in");
		if(!preg_match("~^/~", $path)){
			$path = "/".$path;
		}
		if(!preg_match("~/$~", $path)){
			$path .= "/";
		}
		curl_setopt($this->curl, CURLOPT_POSTFIELDS, array(
			"file" => "@".$file,
			"path" => $path,
			"name" => $name,
			"sha1" => sha1_file($file),
			"overwrite" => $overwrite,
		));
		curl_setopt($this->curl, CURLOPT_URL, $this->server . "/cgi-bin/upload.exe");
		$data = curl_exec($this->curl);
		$out = json_decode($data);
		if($out->error){
			Throw new Exception($out->error); 
		}
		return $out;
	}
	public function get_url($file){
		if(!$this->username) Throw new Exception("Not logged in");
		if(!preg_match("~^/~", $file)){$file = "/".$file;}
		return $this->server . "/" . $this->username . $file;
	}
	public function get($file){
		return file_get_contents($this->get_url($file));
	}
	public function delete($file){
		if(!preg_match("~^/~", $file)){$file = "/".$file;}
		curl_setopt($this->curl, CURLOPT_POSTFIELDS, array(
			"dir" => $file,
			"recursive" => true
		));
		curl_setopt($this->curl, CURLOPT_URL, $this->server . "/cgi-bin/delete.exe");
		$data = curl_exec($this->curl);
		$out = json_decode($data);
		if($out->error){
			Throw new Exception($out->error); 
		}
		return $out->success;
	}
	public function get_used(){
		curl_setopt($this->curl, CURLOPT_POSTFIELDS, array(
			"user" => $this->username
		));
		curl_setopt($this->curl, CURLOPT_URL, $this->server . "/cgi-bin/usage.exe");
		$data = curl_exec($this->curl);
		$out = json_decode($data);
		return $out->used;
	}
}
function upload($file, $auth, $overwrite=false, $path=null, $name=null){
	$ccp = new CloudCP;
	$ccp->login($auth);
	return $ccp->upload($file, $overwrite, $path, $name);
}