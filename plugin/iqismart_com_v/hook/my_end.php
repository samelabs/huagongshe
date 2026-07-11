 
//添加个人中心路径
if($action == 'vapply') {
	if($method == 'GET') {
		include _include(APP_PATH.'plugin/iqismart_com_v/view/htm/my_vapply.htm');
	} elseif($method == 'POST') {
		$uid = $user['uid'];
		$kv = kv_cache_get('iqismart_com_v');
		$type = $kv['type'];
		$count = $kv['count'];
		if($count > 0){
			if($type == 'credits'){
				if( $user['credits'] < $count ){
                    message(-1, '积分不足！请充值！' );
                }
			}elseif($type == 'golds'){
				if( $user['golds'] < $count ){
                    message(-1, '金币不足！请充值！' );
                }
			}elseif($type == 'rmbs'){
				if( $user['rmbs'] < $count ){
                    message(-1, '人民币不足！请充值！' );
                }
			}
		}
                                          
		$v = param('v'); 
		$v_info = param('v_info'); 
		$v_file = param('v_file'); 

		if(empty($v)) message(-1, '请填写认证头衔');
        if(empty($v_info)) message(-1, '请填写证明信息');
        if(empty($v_file)) message(-1, '请上传证明文件');

		
		
		

		// 查询用户是否有申请记录
		$v_apply = v_apply_read('v_apply','uid',$uid);
		if(empty($v_apply)){
			v_apply_create('v_apply', array('uid'=>$uid, 'create_time'=>time(), 'v'=>$v, 'status'=>0, 'v_info'=>$v_info, 'v_file'=>$v_file ));
		}else{
			v_apply_update('v_apply', 'uid', $uid, array( 'create_time'=>time(), 'v'=>$v, 'status'=>0, 'v_info'=>$v_info, 'v_file'=>$v_file  ));
		}
		
        $rb = false;       
        if($count > 0){
			if($type == 'credits'){
                  $rb = user_update($uid,array('credits' => ($user['credits'] - $count) ));
			}elseif($type == 'golds'){
                  $rb = user_update($uid,array('golds' => ($user['golds'] - $count) ));
			}elseif($type == 'rmbs'){
                  $rb = user_update($uid,array('rmbs' => ($user['rmbs'] - $count) ));
			}
		}          
 
	 
		
        db_update('user',array('uid'=>$uid),array('v'=>0));
		message(0, '提交成功！请耐心等待审核');
	}
}elseif($action == 'vresult') {
        if($method == 'GET') {
		include _include(APP_PATH.'plugin/iqismart_com_v/view/htm/my_vapply.htm');
	} 
}

if($action == 'upload'){
	    //上传文件
      $data = param('data', '', FALSE);
      empty($data) AND message(-1, lang('data_is_empty'));
      $data = base64_decode_file_data($data);
      $size = strlen($data);
      $size > 2048000 AND message(-1, lang('filesize_too_large', array('maxsize'=>'2M', 'size'=>$size)));
      $filename = md5($data);
      $path = './upload/v_apply/';
      $url = '/upload/v_apply/'.$filename;
      !is_dir($path) AND (mkdir($path, 0777, TRUE) OR message(-2, lang('directory_create_failed')));
      file_put_contents($path.$filename, $data) OR message(-1, lang('write_to_file_failed'));
       
      message(0, array('a' =>'上传成功','b'=>'失败','c'=>$url ));

}
                  