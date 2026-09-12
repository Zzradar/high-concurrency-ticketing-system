#pragma once
#include <string_view>
namespace ticketing {
// RFC entity-tag list, weak comparison for GET. Malformed lists never validate.
inline bool ifNoneMatch(std::string_view header,std::string_view current){
 auto trim=[](std::string_view v){while(!v.empty()&&(v.front()==' '||v.front()=='\t'))v.remove_prefix(1);while(!v.empty()&&(v.back()==' '||v.back()=='\t'))v.remove_suffix(1);return v;};
 header=trim(header);if(header=="*")return true;
 if(current.starts_with("W/"))current.remove_prefix(2);
 bool matches=false;size_t i=0;
 while(i<header.size()){
  while(i<header.size()&&(header[i]==' '||header[i]=='\t'))++i;
  if(header.substr(i,2)=="W/")i+=2;
  if(i>=header.size()||header[i]!='"')return false;
  const auto begin=i++;
  while(i<header.size()&&header[i]!='"'){const auto ch=static_cast<unsigned char>(header[i]);if(ch<0x21||ch==0x7f)return false;++i;}
  if(i==header.size())return false;
  ++i;matches|=header.substr(begin,i-begin)==current;
  while(i<header.size()&&(header[i]==' '||header[i]=='\t'))++i;
  if(i==header.size())return matches;
  if(header[i++]!=','||i==header.size())return false;
 }
 return false;
}
}
