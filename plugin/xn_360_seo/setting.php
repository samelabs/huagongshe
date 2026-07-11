<?php
!defined('DEBUG') AND exit('Access Denied.');
if ($method == 'GET') {
    $pconfig = setting_get('xn_360_seo');
    $hash = $pconfig['hash'];
    $status_360 = $pconfig['status_360'];
    include _include(APP_PATH . 'plugin/xn_360_seo/setting.htm');
} else {
    $hash = param('hash', '');
    $status_360 = param('status_360', 0);
    $pconfig = array();
    $pconfig['hash'] = $hash;
    $pconfig['status_360'] = $status_360;
    setting_set('xn_360_seo', $pconfig);
    message(0, '提交成功！');
}
