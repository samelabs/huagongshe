<?php exit;
$kv_seo = kv_get('ax_seo');
$f = $kv_seo['seo_mark'];
if($kv_seo['ax_add_open'])
{
	$forum_title= explode('+',$kv_seo['forum_title']);
	
	if($forum['seo_title'])
	{
		$forum['name'] = $forum['seo_title'];
	}

	if($forum_title[0]=='a')
	{
		$a = $kv_seo['ax_add_seo'];

	}elseif ($forum_title[0]=='b') {

		$a = $conf['sitename'];

	}elseif ($forum_title[0]=='c') {
		
		$a = $forum['name'];
	}

	if($forum_title[1]=='a')
	{
		$b = $kv_seo['ax_add_seo'];

	}elseif ($forum_title[1]=='b') {

		$b = $conf['sitename'];

	}elseif ($forum_title[1]=='c') {
		
		$b = $forum['name'];
	}	

	if($forum_title[2]=='a')
	{
		$c = $kv_seo['ax_add_seo'];

	}elseif ($forum_title[2]=='b') {

		$c = $conf['sitename'];

	}elseif ($forum_title[2]=='c') {
		
		$c = $forum['name'];
	}


	$header['title'] = $a.$f.$b.$f.$c;
	$header['mobile_title'] = $a.$f.$b.$f.$c;
	$header['keywords'] = $forum['seo_keywords'];
}						
?>