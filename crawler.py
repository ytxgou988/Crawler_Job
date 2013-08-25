import urllib.request
import re
import datetime
from bs4 import BeautifulSoup
from http.server import HTTPServer,BaseHTTPRequestHandler
from apscheduler.scheduler import Scheduler
import redis
from conf import *  

class article_repository(): 
	#http://redis-py.readthedocs.org/en/latest/
	#https://github.com/MSOpenTech/redis
	#http://code.google.com/p/servicestack/wiki/RedisWindowsDownload#Download_32bit_Cygwin_builds_for_Windows

	#设置redis的ip,端口号以及招聘信息源
	def __init__(self,host,port,sources):
		self.repo = redis.Redis(host=host, port=port)
		self.sources = sources
	
	#不同来源的招聘信息保存在不同的set里，比如Byr
	def add_art(self,article,source):
		self.repo.sadd(source + '_article_id',source + article['id'])
		self.repo.set(source + article['id'],article)

	#根据不同来源来获取招聘信息
	def get_arts_by_source(self,source):
		global SHOW_NUMBER
		art_ids = self.repo.smembers(source + '_article_id')
		arts_with_keyword = []
		arts_without_keyword = []
		index = 0
		for id in art_ids:
			art = eval(self.repo.get(id).decode('UTF-8'))
			if art['interest']:
				arts_with_keyword.append(art)
			else:
				if index < SHOW_NUMBER:
					arts_without_keyword.append(art)
					index += 1
		return {'arts_with_keyword':sorted(arts_with_keyword,key = lambda art : art['id'],reverse=True),
			'arts_without_keyword':sorted(arts_without_keyword,key = lambda art : art['id'],reverse=True)}

	#去除数据库的数据 最好是在测试的时候使用
	def remove(self):
		self.repo.flushdb()

	#保存招聘信息到本地磁盘上
	def save(self):
		return self.repo.save()


class crawler:
	
	#北邮人和水木清华的BBS结构一样，配置基本的HTML元素信息、感兴趣的信息以及需要过滤掉的信息配置
	def __init__(self,title_keyword,limit_keyword,sources):
		self.req_conf = {
			'BYR' : {
				'host' : 'http://bbs.byr.cn',
				'url'  : 'http://bbs.byr.cn/board/JobInfo',
				'url_attr' : {
					'href'   : re.compile('^/article/JobInfo/\d+$'),
					'title'  : None,
					'target' : None
				}
			},
			'NS_XZ' :{
				'host' : 'http://www.newsmth.net/',
				'url'  : 'http://www.newsmth.net/nForum/board/Career_Campus',
				'url_attr' : {
					'href'   : re.compile('^/nForum/article/Career_Campus/\d+$'),
					'title'  : None,
					'target' : None
				}
			},
			'NS_SZ' :{
				'host' : 'http://www.newsmth.net/',
				'url'  : 'http://www.newsmth.net/nForum/board/Career_Upgrade',
				'url_attr' : {
					'href'   : re.compile('^/nForum/article/Career_Upgrade/\d+$'),
					'title'  : None,
					'target' : None
				}
			},
			'NS_LT' :{
				'host' : 'http://www.newsmth.net/',
				'url'  : 'http://www.newsmth.net/nForum/board/ExecutiveSearch',
				'url_attr' : {
					'href'   : re.compile('^/nForum/article/ExecutiveSearch/\d+$'),
					'title'  : None,
					'target' : None
				}
			},
			'headers' : {
				"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
				"Accept-Language": "zh-cn",
				"X-Requested-With" : "XMLHttpRequest"
			}
		}
		self.tgt_time_attr = {
			'class' : re.compile('^title_10\w*$') 
		}
		self.title_keyword = title_keyword
		self.limit_keyword = limit_keyword
		self.job_sources = sources
		self.first_flag = True
	
	#获取目标HTML中的招聘信息
	def get_articles_from_html(self,host,tgt_html,source):
		print(tgt_html)
		req = urllib.request.Request(tgt_html,headers=self.req_conf['headers'])
		rep = urllib.request.urlopen(req)
		art_tags = BeautifulSoup(rep.read().decode('GBK')).find_all('tbody')[0].find_all('tr');
		tgt_arts = []
		for art_tag in art_tags:
			if 'class' not in art_tag.attrs:
				tgt_art = self.extract_information_from_tag(host,art_tag,source)
				if tgt_art is not None:
					tgt_arts.append(tgt_art)
		self.save_articles_in_redis(tgt_arts,source)

	#获取招聘的具体信息，标记感兴趣的信息和过滤掉不感兴趣的招聘信息
	def extract_information_from_tag(self,host,tgt_tag,source):
		tgt_art = {}
		url_tag = tgt_tag.find_all('a',self.req_conf[source]['url_attr']) 
		tgt_art['source'] = source
		tgt_art['title'] = url_tag[0].get_text()
		if self.filter_limit_keyword_in_title(tgt_art['title']) is False: return None
		tgt_art['interest'] = self.title_contain_keyword(tgt_art['title'])
		tgt_art['url'] = host + url_tag[0]['href']
		tgt_art['id'] = re.search('\d+$',tgt_art['url']).group(0)
		time_tags = tgt_tag.find_all('td',self.tgt_time_attr)
		for time_tag in time_tags:
			if len(list(time_tag.descendants)) == 1 :
				pub_time_re = re.search('^\d{4}$',time_tag.get_text()[0:4])
				if type(pub_time_re) is type(None):
					tgt_art['pub_time'] = datetime.date.today().__str__()
				else:
					tgt_art['pub_time'] = time_tag.get_text()
				break
		return tgt_art

	#将获取到的数据保存在redis中
	def save_articles_in_redis(self,tgt_arts,source):
		global art_repo
		for tgt_art in tgt_arts:
			art_repo.add_art(tgt_art,source)

	#过滤不感兴趣的招聘信息
	def filter_limit_keyword_in_title(self,tgt_title):
		if list(filter(lambda keyword : keyword in tgt_title, self.limit_keyword)):
			return False
		else:
			return True

	#获取感兴趣的关键词
	def title_contain_keyword(self,tgt_title):
		return list(filter(lambda keyword : keyword in tgt_title, self.title_keyword))

	#执行爬取工作，程序刚启动时会爬取前两个页面的信息，之后每隔一定时间就只爬取最新的页面
	def run(self):
		if self.first_flag:
			for page in range(1,3):
				for source in self.job_sources:
					print(source)
					self.get_articles_from_html(self.req_conf[source]['host'],self.req_conf[source]['url']+'?p='+ str(page),source)
			self.first_flag = False
		else:
			for source in self.job_sources:
				print(source)
				self.get_articles_from_html(self.req_conf[source]['host'],self.req_conf[source]['url'],source)
		

class request_handler(BaseHTTPRequestHandler):
	#处于简单考虑，使用BaseHTTPRequestHandler处理请求的基本方法
	#除了主页以外，其他具体源的招聘信息是通过页面异步获取
	def do_GET(self):
		global html
		if self.path == '/':
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			self.wfile.write(bytes(html,'UTF-8'))
		elif 'byr' in self.path:
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			self.wfile.write(bytes(self.create_result_page('BYR'),'UTF-8'))
		elif 'nsxz' in self.path:
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			self.wfile.write(bytes(self.create_result_page('NS_XZ'),'UTF-8'))
		elif 'nssz' in self.path:
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			self.wfile.write(bytes(self.create_result_page('NS_SZ'),'UTF-8'))
		elif 'nslt' in self.path:
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			self.wfile.write(bytes(self.create_result_page('NS_LT'),'UTF-8'))
		else:
			self.send_response(404)
			self.send_header("Content-type", "text/html")
			self.end_headers()

	def create_result_page(self,source):
		global art_repo,content,SHOW_NUMBER
		arts = art_repo.get_arts_by_source(source)
		arts_tag_with_keyword = ""
		arts_tag_without_keyword = ""
		for art in arts['arts_with_keyword']:
			tag =  '<tr>'
			tag += '<td>' + art['pub_time'] + '</td>'
			tag += '<td><span class="badge badge-important">' + ('|').join(art['interest']) + '</span></td>'
			tag += '<td><strong><a href=' + art['url'] + '>' + art['title'] + '</a></strong></td>'
			tag += '<td>' + art['source'] + '</td></tr>'
			arts_tag_with_keyword += tag
		index = 0
		for art in arts['arts_without_keyword']:
			if index < SHOW_NUMBER:
				tag =  '<tr>'
				tag += '<td>' + art['pub_time'] + '</td>'
				tag += '<td><strong><a href=' + art['url'] + '>' + art['title'] + '</a></strong></td>'
				tag += '<td>' + art['source'] + '</td></tr>'
				arts_tag_without_keyword += tag
				index += 1
			else:
				break
		return content.format(arts_tag_with_keyword,arts_tag_without_keyword)

#显示页面的模板
html = open('html_model.html','rb').read().decode('UTF-8') 
#显示招聘信息列表的模板
content = open('list_content_model.html','rb').read().decode('UTF-8')
art_repo = article_repository('localhost',6379,JOB_SOURCES)
art_repo.remove()

if __name__ == '__main__':
	crawler_job = crawler(TITLE_INCLUDE_KEYWORD,TITLE_LIMIT_KEYWORD,JOB_SOURCES)
	crawler_job.run()
	sched = Scheduler()
	sched.add_interval_job(crawler_job.run, hours=INTERVAL_TIME_CRAWLER)
	sched.start()	
	
	try:
		# 创建 HTTPSever 服务器，绑定地址：http://127.0.0.1:8080
		server = HTTPServer(('127.0.0.1',8080), request_handler)
		print('Start to Serve:......')	
		# 启动 HTTPServer 服务器  
		server.serve_forever()
	except KeyboardInterrupt:
		print("finish server ...")
		server.socket.close()	  
