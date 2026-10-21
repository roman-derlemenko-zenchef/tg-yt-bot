terraform {
  required_version = ">= 1.6"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.106"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }
}

# The API token comes from the gitignored digitalocean.key next to this file,
# or, if that file doesn't exist, from the DIGITALOCEAN_TOKEN environment
# variable.
provider "digitalocean" {
  token = fileexists("${path.module}/digitalocean.key") ? trimspace(file("${path.module}/digitalocean.key")) : null
}
