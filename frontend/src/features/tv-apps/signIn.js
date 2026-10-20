/** What a TV app needs, in the order its login screen asks for it. */
export function signInDetails(issued) {
  const { server_url: server, password, credential } = issued;
  const auth = `username=${encodeURIComponent(credential.username)}&password=${encodeURIComponent(password)}`;
  return [
    ['server', server],
    ['username', credential.username],
    ['password', password],
    ['m3u', `${server}/get.php?${auth}&type=m3u_plus&output=m3u8`],
    ['epg', `${server}/xmltv.php?${auth}`],
  ];
}
