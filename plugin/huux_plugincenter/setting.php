<?php

/*
Xiuno BBS 4.0 大白插件中心
 */

!defined('DEBUG') and exit('Access Denied.');
define('PLUGIN_HUUX_URL', 'https://www.huux.cc/');
$filename    = APP_PATH . 'model/plugin.func.php'; //需要修改的文件
$filecontent = file_get_contents($filename);
$r           = xn_is_writable($filename);
!$r and message(-1, '没有读写权限，请手动修改 model/plugin.func.php 文件权限为 777');

$action = param(3);

// 插件数据
$huux_plugins = plugin_huux_list_cache();
empty($huux_plugins) AND $huux_plugins = array();
empty($action) AND $action = 'all';

if ($method == 'GET') {

    // 读取插件信息（插件模板使用）
    $jsonfile      = APP_PATH . 'plugin/huux_plugincenter/conf.json';
    $plugin        = xn_json_decode(file_get_contents($jsonfile));
    $plugin_rtmenu = is_array(plugin_rtmenu()) ? plugin_rtmenu() : array();

    // 接口切换
    $in          = strpos($filecontent, 'http://plugin.xiuno.com/') !== false ? 0 : 1;
    $input       = array();
    $input['in'] = form_select('in', array(0 => '官方插件（已经失效，不要切回）', 1 => '大白插件'), $in);

    //展示页面
    $cateid = param(4, 0);
    $page = param(5, 1);
    $pagesize = 30;
    $cond = $cateid ? array('cateid'=>$cateid) : array();
    $action != 'all' AND $cond['price'] = $action == 'official_fee' ? array('>'=>0) : 0;
    $pugin_cates = array(0=>lang('pugin_cate_0'), 1=>lang('pugin_cate_1'), 2=>lang('pugin_cate_2'), 3=>lang('pugin_cate_3'), 4=>lang('pugin_cate_4'));
    $pugin_cate_html = plugin_huux_cate_active($action, $pugin_cates, $cateid, $page);
    $left_menu = array (
        'all'=>array('url'=>url('plugin-setting-huux_plugincenter-all'), 'text'=>'全部'),
        'official_free'=>array('url'=>url('plugin-setting-huux_plugincenter-official_free'), 'text'=>'免费'),
        'official_fee'=>array('url'=>url('plugin-setting-huux_plugincenter-official_fee'), 'text'=>'收费'),
    );
    $total = plugin_huux_total($cond);
    $pluginlist = plugin_huux_list($cond, array('last_date'=>-1), $page, $pagesize);
    $pagination = pagination(url("plugin-setting-huux_plugincenter-$action-$cateid-{page}"), $total, $page, $pagesize);
    $header['title']    = '大白·插件中心';
    $header['mobile_title'] = '大白·插件中心';
 
    include _include(APP_PATH . 'plugin/huux_plugincenter/setting.htm');

} elseif ($action == 'in') {
    $in = param('in');
    $a  = 'http://plugin.xiuno.com/';
    $b  = PLUGIN_HUUX_URL;
    if ($in == 1 && strpos($filecontent, $a) !== false) {
        file_put_contents($filename, str_replace($a, $b, $filecontent));
    } elseif ($in == 0 && strpos($filecontent, $b) !== false) {
        // 1.3版本开始拒绝切回，原因：源官方接口已经失效。
        // file_put_contents($filename, str_replace($b, $a, $filecontent));
        message(0, '切换失败');
    }
    message(0, '切换成功');
}

// 展示页面使用--->

function plugin_huux_total($cond = array()) {
    global $huux_plugins;
    $offlist = $huux_plugins;
    $offlist = arrlist_cond_orderby($offlist, $cond, array(), 1, 1000);
    return count($offlist);
}

function plugin_huux_list($cond = array(), $orderby = array('last_date'=>-1), $page = 1, $pagesize = 200) {
    global $huux_plugins;
    $offlist = $huux_plugins;
    $offlist = arrlist_cond_orderby($offlist, $cond, $orderby, $page, $pagesize);
    return $offlist;
}

function plugin_huux_cate_active($action, $plugin_cate, $cateid, $page) {
    $s = '';
    foreach ($plugin_cate as $_cateid=>$_catename) {
        $url = url("plugin-setting-huux_plugincenter-$action-$_cateid-$page");
        $s .= '<a role="button" class="btn btn btn-secondary'.($cateid == $_cateid ? ' active' : '').'" href="'.$url.'">'.$_catename.'</a>';
    }
    return $s;
}

function plugin_huux_list_cache(){
    $s = DEBUG == 3 ? null : cache_get('plugin_huux_list');
    if ($s === null) {
        $url = PLUGIN_HUUX_URL . "plugin-all-4.htm"; // 获取所有的插件，匹配到3.0以上的。
        $s   = http_get($url);

        // 检查返回值是否正确
        if (empty($s)) {
            return xn_error(-1, '获取插件数据失败。');
        }
        $r = xn_json_decode($s);
        if (empty($r)) {
            return xn_error(-1, '获取插件数据格式不对。');
        }
        $s = $r;
        cache_set('plugin_huux_list', $s, 3600); // 缓存时间 1 小时。
    }
    return $s;
}

function plugin_rtmenu()
{
    $ak  = kv_get('huux_plugincenter_ak');
    $url = PLUGIN_HUUX_URL . "plugin-rtmenu-$ak.htm";
    $s   = http_get($url);
    $arr = xn_json_decode($s);
    if ($arr['code'] == 0) {
        return $arr['message'];
    } else {
        return array();
    }
}

