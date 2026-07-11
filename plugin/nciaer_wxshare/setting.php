<?php
!defined('DEBUG') AND exit('Access Denied.');
if ($method == 'GET') {
    $pconfig = kv_get('nciaer_wxshare');
    $debug = $pconfig['debug'];
    $appid = $pconfig['appid'];
    $appsecret = $pconfig['appsecret'];
    $logo = $pconfig['logo'];
    include _include(APP_PATH . 'plugin/nciaer_wxshare/setting.htm');
} else {
    $debug = param('debug', 0);
    $appid = param('appid');
    $appsecret = param('appsecret');
    $logo = param('logo');
    $pconfig = array();
    $pconfig['debug'] = $debug;
    $pconfig['appid'] = $appid;
    $pconfig['appsecret'] = $appsecret;
    $pconfig['logo'] = $logo;
    kv_set('nciaer_wxshare', $pconfig);
    message(0, '提交成功！');
}
