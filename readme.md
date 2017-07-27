
## Login into Bluemix Containers 
##(basic instructions to run in Docker Community Edition at the end of this file)
```
bx login 
bx cs init
```

## Building Docker Container & Push to Bluemix Registry

```
bx cr login
docker build -t <registry>/bmxbillingreport:latest .
docker push <registry>/bmxbillingreport:latest
```

## Building Redis Docker Container & Push to Bluemix Registry
```
cd redis
docker build -t <registry>/redis-server:latest .
docker push <registry>/redis-server:latest:latest

bx cr images
```


## Verify Kubernetes Cluster
```
bx cs cluster-config kubetest
kubectl get nodes
kubectl proxy&
```

To access Kubernetes cluste go to:  http://127.0.0.1:8001/ui

##Create Service & Define ingress point (modify myingress.yaml to include your host & secretName)
```
kubectl apply -f bmx-billing-report-service.yaml
kubectl apply -f redis/resis-server-service.yaml
kubectl apply -f bmx-billing-report-ingress.yaml
kubectl get svc
```


##Deploy Application to Kubernetes Cluster
```
kubectl create -f bmx-billing-report-deployment.yaml
kubectl create -f redis/redis-server-deployment.yaml
kubectl rollout status deployment/bmx-billing-report-deployment
```

##To run locally in Docker Community Edition
```
docker build -t bmxbillingreport:latest .
docker build -t redis-server:latest redis/.
docker-compose up

```
Browse to http://localhost:5000/bmxbillingreport
