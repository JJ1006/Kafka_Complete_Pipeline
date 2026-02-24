provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = "kind-credit-platform"
}

provider "helm" {
  kubernetes {
    config_path    = "~/.kube/config"
    config_context = "kind-credit-platform"
  }
}
