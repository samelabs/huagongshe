<?php 
!defined('DEBUG') AND exit('Access Denied.');
$action = param(3);

$ax_add_open = param('ax_add_open');
$ax_add_seo = param('ax_add_seo');
$forum_title = param('forum_title');
$thread_title = param('thread_title');
$seo_mark = param('seo_mark');
$ax_seo = kv_get('ax_seo');

if($method == 'GET') {
if(empty($ax_seo)) {
	$ax_seo = array(
		'ax_add_seo'=>$ax_add_seo, 
		'ax_add_open'=>$ax_add_open, 
		'forum_title'=>$forum_title,
		'thread_title'=>$thread_title,
		'seo_mark'=>$seo_mark
	);
	kv_set('ax_seo', $ax_seo);
}			
	
	//$forum_title = form_radio('forum_title', array(0=>"分类名+网站名+自定义长尾词", 1=>"网站名+分类名+自定义长尾词", 2=>"自定义长尾词+网站名+分类名", 3=>"自定义长尾词+分类名+标题名", 4=>"网站名+自定义长尾词+分类名", 5=>"分类名+自定义长尾词+网站名"),$ax_seo['forum_title']);

	$forum_title = form_text('forum_title',$ax_seo['forum_title'],'100%','列表title规则，如a+c+b');

	$thread_title = form_text('thread_title',$ax_seo['thread_title'],'100%','详细页面title规则，如a+d+c+b');


	//$thread_title = form_radio('thread_title', array(0=>"文章标题+分类名+网站名+自定义长尾词", 1=>"文章标题+网站名+分类名+自定义长尾词", 2=>"文章标题+自定义长尾词+网站名+分类名", 3=>"文章标题+自定义长尾词+分类名+标题名", 4=>"文章标题+网站名+自定义长尾词+分类名", 5=>"文章标题+分类名+自定义长尾词+网站名"),$ax_seo['thread_title']);

	$custom = form_text('ax_add_seo', $ax_seo['ax_add_seo'], '100%','自定关键词');
	$open_seo = form_radio_yes_no('ax_add_open', $ax_seo['ax_add_open'],0);

	$seo_mark = form_text('seo_mark', $ax_seo['seo_mark'], '100%','自定义链接符号，默认为 - 。','-');

	include _include(APP_PATH.'plugin/ax_seo/setting.htm');		
	} else {
		

		$ax_seo['ax_add_seo'] = param('ax_add_seo');
		$ax_seo['ax_add_open'] = param('ax_add_open');
		$ax_seo['forum_title'] = param('forum_title');
		$ax_seo['thread_title'] = param('thread_title');
		$ax_seo['seo_mark'] = param('seo_mark');
		kv_set('ax_seo', $ax_seo);	
		message(0, '修改成功');
}
	



?>
