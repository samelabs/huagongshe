<?php
!defined('DEBUG') AND exit('Access Denied.');

class WeiXinShare {

    private $appId;
    private $appSecret;
    private $cachetime;

    public function __construct($appId, $appSecret, $cachetime) {

        $this->appId = $appId;
        $this->appSecret = $appSecret;
        $this->cachetime = $cachetime;
    }
    public function getSignPackage() {

        $jsapiTicket = $this->getJsApiTicket();
        $protocol = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off' || $_SERVER['SERVER_PORT'] == 443) ? "https://" : "http://";
        $url = "$protocol$_SERVER[HTTP_HOST]$_SERVER[REQUEST_URI]";

        $timestamp = time();
        $nonceStr = $this->createNonceStr();

        $string = "jsapi_ticket=$jsapiTicket&noncestr=$nonceStr&timestamp=$timestamp&url=$url";

        $signature = sha1($string);

        $signPackage = array("appId" => $this->appId, "nonceStr" => $nonceStr, "timestamp" => $timestamp, "url" => $url, "signature" => $signature, "rawString" => $string);
        return $signPackage;
    }

    private function getJsApiTicket() {

        $data = kv_get('nciaer_jsapi_ticket');
        if(!empty($data)) {
            if ($data['expire_time'] > time()) {
                $ticket = $data['jsapi_ticket'];
            } else {
                $ticket = $this->updateTicket();
            }
        } else {
            $ticket = $this->updateTicket();
        }

        return $ticket;
    }

    private function updateTicket() {

        $accessToken = $this->getAccessToken();
        $url = "https://api.weixin.qq.com/cgi-bin/ticket/getticket?type=jsapi&access_token=$accessToken";
        $res = json_decode(file_get_contents($url));
        $ticket = $res->ticket;
        if ($ticket) {
            $data = array();
            $data['expire_time'] = time() + $this->cachetime;
            $data['jsapi_ticket'] = $ticket;
            kv_set("nciaer_jsapi_ticket", $data);
        }
        return $ticket;
    }

    private function updateToken() {

        $url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=$this->appId&secret=$this->appSecret";
        $res = json_decode(file_get_contents($url));
        $access_token = $res->access_token;
        if ($access_token) {
            $data = array();
            $data['expire_time'] = time() + $this->cachetime;
            $data['access_token'] = $access_token;
            kv_set("nciaer_access_token", $data);
        }

        return $access_token;
    }

    private function getAccessToken() {

        $data = kv_get('nciaer_access_token');
        if(!empty($data)) {
            if ($data['expire_time'] > time()) {
                $access_token = $data['access_token'];
            } else {
                $access_token = $this->updateToken();
            }
        } else {
            $access_token = $this->updateToken();
        }
        return $access_token;
    }

    private function createNonceStr($length = 16) {
        $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        $str = "";
        for ($i = 0; $i < $length; $i++) {
            $str .= substr($chars, mt_rand(0, strlen($chars) - 1), 1);
        }
        return $str;
    }
}