<?php
 function v_apply_create($form, $arr) {
	$r = db_insert($form, $arr);
	return $r;
}
function v_apply_update($form, $field, $id, $arr) {
	$r = db_update($form, array($field=>$id), $arr);
	return $r;
}
function v_apply_read($form, $field, $id) {
	$thread = db_find_one($form, array($field=>$id));
	return $thread;
}
function v_apply_find($form, $field, $cond = array(), $orderby = array(), $page = 1, $pagesize = 10) {
	$arrlist = db_find($form, $cond, $orderby, $page, $pagesize, $field, array($field));
	if(empty($arrlist)) return array();
	$tidarr = arrlist_values($arrlist, $field);
	$sg_signlist = db_find($form, array($field=>$tidarr), $orderby, 1, $pagesize, $field);
	return $sg_signlist;
}

// bootstrap 翻页，命名与 bootstrap 保持一致
function pagination_ajax($url, $totalnum, $page, $pagesize = 20) {
    $totalpage = ceil($totalnum / $pagesize);
    if($totalpage < 2) return '';
    $page = min($totalpage, $page);
    $shownum = 5;   // 显示多少个页 * 2

    $start = max(1, $page - $shownum);
    $end = min($totalpage, $page + $shownum);

    // 不足 $shownum，补全左右两侧
    $right = $page + $shownum - $totalpage;
    $right > 0 && $start = max(1, $start -= $right);
    $left = $page - $shownum;
    $left < 0 && $end = min($totalpage, $end -= $left);

    $s = '';
    $page != 1 && $s .= pagination_tpl_ajax(str_replace('{page}', $page-1, $url), '«', '');
    if($start > 1) $s .= pagination_tpl_ajax(str_replace('{page}', 1, $url),'1 '.($start > 2 ? '... ' : ''));
    for($i=$start; $i<=$end; $i++) {
        $s .= pagination_tpl_ajax(str_replace('{page}', $i, $url), $i, $i == $page ? ' active' : '');
    }
    if($end != $totalpage) $s .= pagination_tpl_ajax(str_replace('{page}', $totalpage, $url), ($totalpage - $end > 1 ? '... ' : '').$totalpage);
    $page != $totalpage && $s .= pagination_tpl_ajax(str_replace('{page}', $page+1, $url), '»');
    return $s;
}
?>