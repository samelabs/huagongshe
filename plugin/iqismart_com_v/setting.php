<?php !defined('DEBUG') AND exit('Access Denied.');
$action = param(3);
if(empty($action)) {
    if ($method == 'GET') {//设置页面
      	$page = 1; //起始页
      	$pagesize = 20;
        $applying_list ='';//用于列表回调
        $applyed_list ='';//用于列表回调
        $applying_pagination= '';
        $applyed_pagination = '';
      
       
       
	     $applying_num = db_count('v_apply',array('status'=>0)); 
	     $list = db_find('v_apply', $cond = array('status'=>0), $orderby = array('create_time'=>-1), $page, $pagesize, $key ='', $col = array('uid','v','v_info','v_file','status','remark','create_time'), $d = NULL);
            foreach ($list as $key){  
                $user = db_find_one('user', array('uid'=>$key['uid']));
                $applying_list .= '<tr><td>'.$key['uid'].'</td><td>'.$user['username'].'</td><td>'.$key['v'].'</td><td>'.$key['v_info'].'</td><td><a href="//'.$_SERVER['HTTP_HOST'].$key['v_file'].'" target="_blank" data-toggle="tooltip" data-placement="top">证明文件</td><td>'.date('Y-n-j', $key['create_time']).'</td><td><button onclick="pass('.$key['uid'].')" class=" btn btn-success btn-sm" style="margin-right:10px;" >通过</button><button onclick="reject('.$key['uid'].')" class=" btn btn-danger btn-sm" >拒绝</button></td></tr>';
            }
		 $applying_pagination = pagination_ajax("{page}", $applying_num, $page, $pagesize);
       
      
        
	     $applyed_num = db_count('v_apply',array('status'=>1)); 
	     $list = db_find('v_apply', $cond = array('status'=>1), $orderby = array('create_time'=>-1), $page, $pagesize, $key ='', $col = array('uid','v','v_info','v_file','status','remark','create_time'), $d = NULL);
            foreach ($list as $key){  
                $user = db_find_one('user', array('uid'=>$key['uid']));
                $applyed_list .= '<tr><td>'.$key['uid'].'</td><td>'.$user['username'].'</td><td>'.$key['v'].'</td><td>'.$key['v_info'].'</td><td><a href="//'.$_SERVER['HTTP_HOST'].$key['v_file'].'" target="_blank" data-toggle="tooltip" data-placement="top">证明文件</td><td>'.date('Y-n-j', $key['create_time']).'</td>  </tr>';
            }
		 $applyed_pagination = pagination_ajax("{page}", $applyed_num, $page, $pagesize);
       
        include _include(APP_PATH . 'plugin/iqismart_com_v/setting.htm');
    } elseif ($method == "POST") {
        $op=param('op'); 
      	$username=param('username');
      
        if($op==0) {
          	if(empty($username)) die();
            $_user = db_find_one('user',array('username'=>$username));
            if($_user) message(0,$_user['v']);
            else message(-1,"NO_SUCH_USER");
        } elseif($op==1) {
          	if(empty($username)) die();
            $v = param('val');
            $_user = db_find_one('user',array('username'=>$username));
            if($_user){
                db_update('user',array('username'=>$username),array('v'=>$v));
                message(0,'设置成功！');
            }
            else message(-1,"NO_SUCH_USER");
        }elseif($op==2) {
          	 //设置参数
            $type = param('type');
          	$count = param('count');
           
          	$kv = array();
            if(!$kv) {
                $kv = array('type'=>$type, 'count'=>$count);
               	kv_cache_delete('iqismart_com_v');
                kv_set('iqismart_com_v', $kv);
             	  
            }

            message(0,'设置成功！');
        }
    }
}


if($action == 'vapplyinglist') {
            $page = param('l');
            $ajax_list =''; //用于列表回调
            $num = db_count('v_apply',array('status'=>0));   
            $arrlist = db_find('v_apply', $cond =array('status'=>0), $orderby = array('create_time'=>-1), $page, $pagesize, $key ='', $col = array('uid','v','v_info','v_file','status','remark','create_time'), $d = NULL);
            foreach ($arrlist as $key){  
                $user = db_find_one('user', array('uid'=>$key['uid']));
                $ajax_list .= '<tr><td>'.$key['uid'].'</td><td>'.$user['username'].'</td><td>'.$key['v'].'</td><td>'.$key['v_info'].'</td><td><a href="//'.$_SERVER['HTTP_HOST'].$key['v_file'].'" target="_blank" data-toggle="tooltip" data-placement="top">证明文件</td><td>'.date('Y-n-j', $key['create_time']).'</td><td><button onclick="pass('.$key['uid'].')" class="btn-success" style="margin-right:10px;" >通过</button><button onclick="reject('.$key['uid'].')" class="btn-danger" >拒绝</button></td></tr>';
            }
            $pagination = pagination_ajax("{page}", $num, $page, $pagesize);//用于分页回调
            message(0, array('a' => $ajax_list ,'b'=> $pagination,'c'=> $page));
}	  
if($action == 'vpassedlist') {
            $page = param('uid');
            $ajax_list =''; //用于列表回调
            $num = db_count('v_apply',array('status'=>-1)); 
             $arrlist = db_find('v_apply', $cond =array('status'=>0), $orderby = array('create_time'=>-1), $page, $pagesize, $key ='', $col = array('uid','v','v_info','v_file','status','remark','create_time'), $d = NULL);
            foreach ($arrlist as $key){  
                $ajax_list .= '<tr><td>'.$key['aid'].'</td><td><i class="icon-folder-open"></i>'.$key['filename'].'</td><td><a href="//'.$_SERVER['HTTP_HOST'].'/'.$conf['upload_url'].'attach/'.$key['filename'].'" target="_blank" data-toggle="tooltip" data-placement="top" title="'.($key['filetype']=='image'?'('.$key['width'].'px * '.$key['height'].'px)':'').'">'.$key['orgfilename'].'</td><td>'.$key['filetype'].'</td><td>'.format_bytes($key['filesize']).'</td><td>'.date('Y-n-j', $key['create_date']).'</td></tr>';
            }
            $pagination = pagination_ajax("{page}", $num, $page, $pagesize);//用于分页回调
            message(0, array('a' => $ajax_list ,'b'=> $pagination,'c'=> $page));
	 
}

if($action == 'pass') {
  			$uid = param('uid');
  			$apply = db_find_one('v_apply', $cond =array('uid'=>$uid));
  			 db_update('user',array('uid'=>$uid),array('v'=>$apply['v']));
            v_apply_update('v_apply', 'uid', $uid, array('status'=>1 ));
  
  			$message = '恭喜！加V认证成功！';
  			notice_send(1, $uid, $message, 3); // 3:系统通知
            message(0, '加V认证成功');
}

if($action == 'reject') {
  			$uid = param('1'); 
            v_apply_update('v_apply', 'uid', $uid, array('status'=>-1 ));
            message(0, '已拒绝');
}
?>