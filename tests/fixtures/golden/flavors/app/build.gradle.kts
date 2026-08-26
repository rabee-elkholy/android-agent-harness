android {
    flavorDimensions += "env"
    productFlavors {
        create("staging") { dimension = "env" }
        create("prodClient") { dimension = "env" }
        isDefault = true
    }
}
