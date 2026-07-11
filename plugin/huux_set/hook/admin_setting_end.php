<?php exit;
elseif($action == 'extend') {
    
    if($method == 'GET') {
        $input = array();
        $input['runlevel_reason'] = form_textarea('runlevel_reason', $conf['runlevel_reason'], '100%', 100);
        $input['url_rewrite_on'] = form_radio_yes_no('url_rewrite_on', $conf['url_rewrite_on']); 
        $input['cdn_on'] = form_radio_yes_no('cdn_on', $conf['cdn_on']); 
        $input['admin_bind_ip'] = form_radio_yes_no('admin_bind_ip',$conf['admin_bind_ip']); 
        $input['pagesize'] = form_text('pagesize', $conf['pagesize'], 100); 
        $input['postlist_pagesize'] = form_text('postlist_pagesize', $conf['postlist_pagesize'], 100); 
        $input['site_keywords'] = form_text('site_keywords', empty($conf['site_keywords'])?'':$conf['site_keywords']); 
        $input['user_create_io'] = form_radio_yes_no('user_create_io', empty($conf['user_create_io'])? 0 :$conf['user_create_io']);
        $input['attach_maxsize'] = form_text('attach_maxsize', empty($conf['attach_maxsize'])? 20480000 :$conf['attach_maxsize']);

        $header['title'] = lang('admin_setting_extend');
        $header['mobile_title'] = lang('admin_setting_extend');
        include _include(APP_PATH.'plugin/huux_set/view/htm/setting_extend.htm');
    } else {
        // ✅ 修复：使用 $conf 中的当前值作为默认值
        $runlevel_reason = param('runlevel_reason', $conf['runlevel_reason'], FALSE);
        $url_rewrite_on = param('url_rewrite_on', $conf['url_rewrite_on']); 
        $cdn_on = param('cdn_on', $conf['cdn_on']); 
        $admin_bind_ip = param('admin_bind_ip', $conf['admin_bind_ip']); 
        $pagesize = param('pagesize', $conf['pagesize']); 
        $postlist_pagesize = param('postlist_pagesize', $conf['postlist_pagesize']);  
        $site_keywords = param('site_keywords', $conf['site_keywords'], FALSE); 
        $user_create_io = param('user_create_io', $conf['user_create_io']); 
        $attach_maxsize = param('attach_maxsize', $conf['attach_maxsize']); 

        $replace = array();
        $replace['runlevel_reason'] = $runlevel_reason;
        $replace['url_rewrite_on'] = $url_rewrite_on;
        $replace['cdn_on'] = $cdn_on;
        $replace['admin_bind_ip'] = $admin_bind_ip;
        $replace['pagesize'] = $pagesize;
        $replace['postlist_pagesize'] = $postlist_pagesize; 
        $replace['site_keywords'] = $site_keywords;
        $replace['user_create_io'] = $user_create_io;
        $replace['attach_maxsize'] = $attach_maxsize;

        // ✅ 确保 file_replace_var 已替换为安全版
        file_replace_var(APP_PATH.'conf/conf.php', $replace);
        message(0, lang('save_successfully'));
    }
}
?>