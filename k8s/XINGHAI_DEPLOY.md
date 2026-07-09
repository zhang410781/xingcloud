# Xinghai K8S Deploy

鐩爣鏈嶅姟鍣細`10.132.46.52`
鐩爣鐩綍锛歚/xing/devops`
闀滃儚浠撳簱锛歚registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent:a1.02`
榛樿鍩熷悕锛歚xinghai.example.com`
瀛樺偍绫伙細`nfs-client`
IngressClass锛歚nginx`

骞冲彴榛樿瓒呯骇鐢ㄦ埛淇濇寔椤圭洰榛樿鍊硷細`admin / Admin@123456`銆?MySQL 鐢ㄦ埛銆丮ySQL 瀵嗙爜銆丮ySQL root 瀵嗙爜浣跨敤锛歚xinghai / xinghaik8s`銆?K8S 闆嗙兢浣跨敤 Docker锛屼笉闇€瑕侀澶?`imagePullSecrets`銆?
## 鍩虹闀滃儚

绾夸笂鏋勫缓榛樿浣跨敤鍗庝负浜?SWR 闀滃儚锛?
```text
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:20-alpine
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim
```

涔熷彲浠ュ湪鏋勫缓鏃惰鐩栵細

```bash
docker build \
  --build-arg NODE_BASE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:20-alpine \
  --build-arg PYTHON_BASE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim \
  -t registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent:a1.02 .
```

## 1. 涓婁紶婧愮爜

鍦ㄦ湰鏈?PowerShell 鎵ц锛?
```powershell
$src="<鏈湴椤圭洰鏍圭洰褰?"
scp -r "$src\*" root@10.132.46.52:/xing/devops/
```

## 2. 鐧诲綍鏈嶅姟鍣ㄥ苟妫€鏌ョ幆澧?
```bash
ssh root@10.132.46.52
cd /xing/devops
bash k8s/check-env.sh
```

閲嶇偣纭锛?
- `kubectl get sc` 鏈?`nfs-client`
- `kubectl get ingressclass` 鏈?`nginx`
- `docker` 鍙敤
- `/xing/devops` 鏄綋鍓嶆簮鐮佺洰褰?
## 3. 鐧诲綍闃块噷浜戦暅鍍忎粨搴?
濡傛灉 `docker push` 鎻愮ず鏈櫥褰曪紝鍐嶆墽琛岋細

```bash
docker login --username=xinghai registry.cn-hangzhou.aliyuncs.com
```

瀵嗙爜鎸変綘鐨勪粨搴撳疄闄呭瘑鐮佽緭鍏ャ€?
## 4. 浠庢簮鐮佹瀯寤哄苟閮ㄧ讲

```bash
cd /xing/devops
chmod +x k8s/deploy.sh k8s/check-env.sh
bash k8s/deploy.sh
```

榛樿浼氭瀯寤哄苟鎺ㄩ€侊細

```text
registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent:a1.02
```

鍚庣画鍙戞柊鐗堟湰锛?
```bash
TAG=a1.02 bash k8s/deploy.sh
```

## 5. 鏌ョ湅鐘舵€?
```bash
kubectl get pods -n xing-cloud -o wide
kubectl get pvc -n xing-cloud
kubectl get ingress -n xing-cloud
kubectl logs -n xing-cloud deploy/xing-cloud-app --tail=200
kubectl logs -n xing-cloud deploy/xing-cloud-scheduler --tail=200
```

濡傛灉鍒濆鍖栧け璐ワ細

```bash
kubectl logs -n xing-cloud job/xing-cloud-init --tail=300
```

## 6. 鐢熸垚闆嗙兢瀵煎叆 KubeConfig

K8S 闆嗙兢绠＄悊椤甸潰鎸?Kuboard 鐨勪範鎯尯鍒嗏€滃彧璇荤敤鎴封€濆拰鈥滅鐞嗙敤鎴封€濄€傚彲鍦ㄧ洰鏍囬泦缇ょ敓鎴愪袱浠?kubeconfig 鍚庡鍏ワ細

```bash
cd /xing/devops
chmod +x k8s/create-kubeconfig-users.sh
OUT_DIR=/xing/devops bash k8s/create-kubeconfig-users.sh
```

鐢熸垚鏂囦欢锛?
```text
/xing/devops/readonly-user-kubeconfig.yaml  # 鍙鐢ㄦ埛锛屾煡鐪嬭妭鐐?Service/StorageClass 绛夎祫婧?/xing/devops/kubeconfig.yaml                # 绠＄悊鐢ㄦ埛锛宑luster-admin 鏉冮檺
```

鍦ㄩ〉闈㈡柊澧為泦缇ゆ椂锛岄€夋嫨瀵瑰簲璁块棶韬唤骞剁矘璐村搴?kubeconfig銆傝繛鎺ユ祴璇曚細妫€鏌ヨ妭鐐瑰垪琛ㄣ€丼ervice 鍒楄〃銆丼torageClass 鍒楄〃鏉冮檺銆?
## 7. 涓存椂楠岃瘉璁块棶

濡傛灉 DNS 杩樻病瑙ｆ瀽 `xinghai.example.com`锛屽厛鍦ㄦ湰鏈?hosts 鍔狅細

```text
10.105.118.19 xinghai.example.com
```

`10.105.118.19` 鏄綘鐜版湁 Ingress 鏆撮湶鍦板潃锛涘鏋滃悗缁?`kubectl get ingress -n xing-cloud` 鏄剧ず浜嗘柊鍦板潃锛屼互鏂板湴鍧€涓哄噯銆?
涔熷彲浠ヤ复鏃剁鍙ｈ浆鍙戯細

```bash
kubectl port-forward -n xing-cloud svc/xing-cloud-app 8000:8000 --address 0.0.0.0
```

鐒跺悗璁块棶锛?
```text
http://10.132.46.52:8000
```
